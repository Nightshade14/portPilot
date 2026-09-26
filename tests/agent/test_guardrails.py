"""Guardrail tests: disallowed tool denied, install-like shell denied with guidance,
load_tool capped."""

from __future__ import annotations

from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn
from strands import Agent, tool

from portpilot.agent.core_tools import StepContext, build_core_tools
from portpilot.agent.guard import INSTALL_LIKE_GUIDANCE, StepPolicy
from portpilot.core.models import Budgets, ShortTermPlan, StepBudget, ToolPick


def _step(**overrides) -> ShortTermPlan:
    defaults = {
        "step_id": "step_1",
        "run_id": "run_1",
        "seq": 1,
        "phase_id": "p1",
        "title": "t",
        "objective": "o",
        "budget": StepBudget(max_turns=10, max_tokens=100_000, max_minutes=10),
    }
    defaults.update(overrides)
    return ShortTermPlan(**defaults)


def _tool_result_texts(agent) -> str:
    tool_results = [
        block["toolResult"]
        for msg in agent.messages
        for block in msg.get("content", [])
        if "toolResult" in block
    ]
    return " ".join(c.get("text", "") for r in tool_results for c in r.get("content", []))


def test_disallowed_tool_is_denied(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_1")
    deps.run_store.create_run(run)
    step = _step()
    deps.run_store.save_step(step)

    ctx = StepContext(deps=deps, run=run, step=step)
    core_tools = build_core_tools(ctx)
    policy = StepPolicy(deps=deps, run=run, step=step, ctx=ctx)

    @tool
    def not_a_core_tool() -> str:
        """Not in the allow-list."""
        return "ran"

    model = ScriptedModel(
        turns=[
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("not_a_core_tool", {})], text="denied, as expected"
            ),
        ]
    )
    agent = Agent(model=model, tools=[*core_tools, not_a_core_tool], interventions=[policy])
    ctx._agent_ref = agent

    agent("call not_a_core_tool")

    denial_text = _tool_result_texts(agent)
    assert denial_text, "expected a tool result (the denial) in the conversation"
    assert "not_a_core_tool" in denial_text
    assert "not in this step's allowed tool set" in denial_text


def test_install_like_shell_command_denied_with_guidance(sandbox_root):
    def shell_guard(command: str) -> str | None:
        if "apt-get install" in command or "pip install" in command:
            return f"command '{command}' looks like a package install"
        return None

    deps = make_deps(sandbox_root=sandbox_root, shell_guard=shell_guard)
    run = make_run(run_id="run_2")
    deps.run_store.create_run(run)
    step = _step(
        step_id="step_2",
        run_id="run_2",
        selected_tools=[ToolPick(name="shell", version=1, reason="test")],
    )
    deps.run_store.save_step(step)

    ctx = StepContext(deps=deps, run=run, step=step)
    core_tools = build_core_tools(ctx)
    policy = StepPolicy(deps=deps, run=run, step=step, ctx=ctx)

    @tool
    def shell(command: str) -> str:
        """Run a shell command."""
        return f"ran: {command}"

    model = ScriptedModel(
        turns=[
            ScriptedTurn(
                tool_calls=[ScriptedToolCall("shell", {"command": "apt-get install curl"})],
                text="got denied",
            ),
        ]
    )
    agent = Agent(model=model, tools=[*core_tools, shell], interventions=[policy])
    ctx._agent_ref = agent

    agent("install curl")

    denial_text = _tool_result_texts(agent)
    assert "package install" in denial_text
    assert INSTALL_LIKE_GUIDANCE in denial_text


def test_real_docker_tool_names_are_allowed(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_docker_tools")
    deps.run_store.create_run(run)
    step = _step(step_id="step_docker_tools", run_id=run.run_id)
    ctx = StepContext(deps=deps, run=run, step=step)
    policy = StepPolicy(deps=deps, run=run, step=step, ctx=ctx)

    assert {"sandbox_shell", "sandbox_file_editor"} <= policy.allowed_tool_names()


class _OneToolLibrary:
    """A `ToolLibrary` stand-in with exactly one candidate, for the load_tool cap test."""

    def candidates(self, query, filters=None, limit=20):
        from portpilot.core.models import ToolCard

        return [ToolCard(name="extra_tool", version=1, description="d", when_to_use="w")]

    def get(self, name, version=None):
        from portpilot.core.models import ToolRecord

        return ToolRecord(
            name=name,
            version=1,
            description="d",
            when_to_use="w",
            input_schema={},
            output_schema={},
            files={"main.py": "def run(p): return {}"},
        )

    def as_agent_tool(self, record, run_id):
        from strands.types.tools import AgentTool

        class _T(AgentTool):
            @property
            def tool_name(self):
                return record.name

            @property
            def tool_spec(self):
                return {
                    "name": record.name,
                    "description": "d",
                    "inputSchema": {"json": {"type": "object", "properties": {}}},
                }

            @property
            def tool_type(self):
                return "lib"

            async def stream(self, tool_use, invocation_state, **kwargs):
                yield {
                    "toolUseId": tool_use["toolUseId"],
                    "status": "success",
                    "content": [{"text": "ok"}],
                }

        return _T()

    def record_use(self, *a, **k):
        pass

    def propose(self, *a, **k):
        raise NotImplementedError

    def validate(self, *a, **k):
        raise NotImplementedError

    def promote(self, *a, **k):
        raise NotImplementedError


def test_load_tool_capped_at_max_mid_step_loads(sandbox_root):
    deps = make_deps(
        sandbox_root=sandbox_root,
        tool_library=_OneToolLibrary(),
    )
    run = make_run(run_id="run_3", budgets=Budgets(max_mid_step_loads=1))
    deps.run_store.create_run(run)
    step = _step(step_id="step_3", run_id="run_3")
    deps.run_store.save_step(step)

    ctx = StepContext(deps=deps, run=run, step=step)
    core_tools = build_core_tools(ctx)
    load_tool = next(t for t in core_tools if t.tool_name == "load_tool")

    r1 = load_tool(name="extra_tool", reason="first load")
    assert "loaded extra_tool" in r1
    assert ctx.mid_step_loads == 1

    r2 = load_tool(name="extra_tool2", reason="second load, should be refused")
    assert "refused" in r2
    assert ctx.mid_step_loads == 1
