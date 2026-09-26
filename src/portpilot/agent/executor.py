"""Fresh-agent-per-step execution loop (lane-a.md build step 8).

`execute_step` builds one `strands.Agent` for the STP: executor model, core + selected
+ sandbox tools, compaction manager, a session manager (when configured), the
`ContextOffloader` (when configured), `StepPolicy`, and hooks recording `tool_call` /
`tool_result` / `tool_error` plus accumulating `Usage`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from portpilot.core.models import Run, ShortTermPlan, Usage

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

logger = logging.getLogger(__name__)

BRIEF_TOKEN_CAP = 3_000
CONTINUE_NUDGE = "continue; call complete_step when the acceptance checks should pass"


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"


def build_brief(
    step: ShortTermPlan,
    ltp_excerpt: str,
    digest: str,
    lessons_and_gotchas: list[dict[str, Any]],
) -> str:
    """The STP brief pinned as the first message (build step 8): STP, LTP excerpt,
    digest, and the top-5 relevant lessons/gotchas, capped at about 3k tokens."""

    parts = [
        f"## Step: {step.title}",
        f"Objective: {step.objective}",
        f"Inputs: {step.inputs}",
        f"Acceptance checks: {[c.command for c in step.acceptance]}",
        f"Capability hints: {step.capability_hints}",
        "",
        "## Relevant long-term plan excerpt",
        ltp_excerpt,
        "",
        "## Run digest",
        digest or "(none yet -- this is the first step)",
        "",
        "## Top relevant lessons and gotchas",
    ]
    for item in lessons_and_gotchas[:5]:
        parts.append(
            f"- [{item.get('kind', 'lesson')}] {item.get('title', '')}: {item.get('body', '')}"
        )
    return _truncate_to_tokens("\n".join(parts), BRIEF_TOKEN_CAP)


class _RecordingHooks:
    """HookProvider recording tool_call / tool_result / tool_error and Usage per step."""

    def __init__(self, deps: AgentDeps, run: Run, step: ShortTermPlan, ctx: Any) -> None:
        self.deps = deps
        self.run = run
        self.step = step
        self.ctx = ctx
        self.usage = Usage()

    def register_hooks(self, registry: Any, **kwargs: Any) -> None:
        from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent

        registry.add_callback(BeforeToolCallEvent, self._on_before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._on_after_tool_call)

    def _on_before_tool_call(self, event: Any) -> None:
        args_preview = json.dumps(event.tool_use.get("input", {}))[:500]
        self.deps.run_store.log_event(
            self.run.run_id,
            "tool_call",
            self.step.step_id,
            {"tool": event.tool_use.get("name", ""), "args_preview": args_preview},
        )

    def _on_after_tool_call(self, event: Any) -> None:
        tool_name = event.tool_use.get("name", "")
        self.usage.tool_calls += 1
        result = event.result
        if isinstance(result, Exception):
            self.deps.run_store.log_event(
                self.run.run_id,
                "tool_error",
                self.step.step_id,
                {"tool": tool_name, "error": str(result)},
            )
            self.ctx.mark_used(tool_name, ok=False)
            return

        ok = result.get("status") == "success"
        preview = ""
        for block in result.get("content", []):
            if "text" in block:
                preview = block["text"][:500]
                break
        artifact_id = None
        if len(preview) >= 500:
            artifact_id = self.deps.run_store.put_artifact(
                self.run.run_id,
                self.step.step_id,
                "tool_output",
                result.get("content", []),
                name=f"{tool_name}_output",
            )
        self.deps.run_store.log_event(
            self.run.run_id,
            "tool_result",
            self.step.step_id,
            {
                "tool": tool_name,
                "ok": ok,
                "seconds": round(event.duration or 0.0, 3),
                "preview": preview,
                **({"artifact_id": artifact_id} if artifact_id else {}),
            },
        )
        self.ctx.mark_used(tool_name, ok=ok)


def _build_session_manager(deps: AgentDeps, session_id: str) -> Any | None:
    if deps.session_manager_factory is None:
        return None
    return deps.session_manager_factory(session_id)


def _build_conversation_manager(deps: AgentDeps, run: Run, step: ShortTermPlan):
    from strands import Agent

    from portpilot.agent.compaction import LoggedSummarizingConversationManager

    summarization_agent = Agent(
        model=deps.model_factory("aux"),
        tools=[],
        system_prompt="You summarize conversations concisely.",
    )
    return LoggedSummarizingConversationManager(
        deps=deps,
        run_id=run.run_id,
        step_id=step.step_id,
        summarization_agent=summarization_agent,
        pin_first=1,
        preserve_recent_messages=8,
        proactive_compression={"compression_threshold": 0.7},
    )


def _build_plugins(deps: AgentDeps) -> list[Any]:
    if deps.offload_storage is None:
        return []
    from strands.vended_plugins.context_offloader import ContextOffloader

    return [
        ContextOffloader(storage=deps.offload_storage, max_result_tokens=2500, preview_tokens=200)
    ]


def _fallback_sandbox_tools(deps: AgentDeps, run_id: str) -> list[Any]:
    """Minimal `shell` / `file_editor` tools built directly on `SandboxManager.exec` /
    `write_file` / `read_file`, used when `SandboxManager.sandbox().get_tools()` is
    unavailable (e.g. the frozen `LocalSandboxManager.sandbox()` in `core/fakes.py`
    currently raises -- `NotASandboxLocalEnvironment()` takes no constructor args, so
    `working_dir=...` fails; reported to the Lead as a core/ bug, not fixed here).

    Without this fallback the executor has no way to touch the workspace at all: it can
    only call core tools, so it can never actually do a step's work and will nudge in
    place until the turn budget is exhausted. This keeps a step productive even while
    that core bug is open."""

    from strands import tool

    @tool
    def shell(command: str) -> str:
        """Run a shell command in the run's workspace (/workspace/repo)."""
        result = deps.sandbox.exec(run_id, command, timeout_s=120)
        parts = [f"exit_code={result.exit_code}"]
        if result.stdout:
            parts.append(f"stdout:\n{result.stdout[:4000]}")
        if result.stderr:
            parts.append(f"stderr:\n{result.stderr[:2000]}")
        return "\n".join(parts)

    @tool
    def file_editor(action: str, path: str, content: str = "") -> str:
        """Read or write a file in the run's workspace.

        Args:
            action: "read" or "write".
            path: File path, absolute or relative to /workspace/repo.
            content: New file content (only used when action="write").
        """
        target = path if path.startswith("/workspace") else f"/workspace/repo/{path}"
        if action == "write":
            deps.sandbox.write_file(run_id, target, content)
            return f"wrote {len(content)} bytes to {target}"
        if action == "read":
            try:
                return deps.sandbox.read_file(run_id, target)
            except OSError as exc:
                return f"could not read {target}: {exc}"
        return f"unknown action {action!r}; use 'read' or 'write'"

    return [shell, file_editor]


def execute_step(
    deps: AgentDeps,
    run: Run,
    step: ShortTermPlan,
    *,
    ltp_excerpt: str = "",
    digest: str = "",
    lessons_and_gotchas: list[dict[str, Any]] | None = None,
    max_nudges: int = 30,
) -> ShortTermPlan:
    """Run the executor loop for `step` until `complete_step` is called or the budget
    runs out. On resume, a step already `running` with a session continues it (the
    session manager restores prior history; see loop.py for the resume decision)."""

    from strands import Agent

    from portpilot.agent.core_tools import StepContext, build_core_tools
    from portpilot.agent.guard import BudgetExceeded, LeaseLost, StepPolicy

    ctx = StepContext(deps=deps, run=run, step=step)
    core_tools = build_core_tools(ctx)

    sandbox_tools: list[Any] = []
    try:
        sandbox = deps.sandbox.sandbox(run.run_id)
        sandbox_tools = sandbox.get_tools()
        if not sandbox_tools:
            raise RuntimeError("sandbox returned no agent tools")
    except Exception as exc:  # noqa: BLE001 -- sandbox tools are best-effort; fall back below
        logger.warning(
            "sandbox.get_tools() failed for run %s: %s -- falling back to exec/write_file/"
            "read_file tools so the step can still touch the workspace",
            run.run_id,
            exc,
        )
        sandbox_tools = _fallback_sandbox_tools(deps, run.run_id)

    selected_agent_tools: list[Any] = []
    if deps.tool_library is not None:
        for pick in step.selected_tools:
            try:
                record = deps.tool_library.get(pick.name, pick.version)
                selected_agent_tools.append(deps.tool_library.as_agent_tool(record, run.run_id))
            except Exception as exc:  # noqa: BLE001 -- a picked tool that no longer resolves is skipped, not fatal
                logger.warning(
                    "could not load selected tool %s@%s: %s", pick.name, pick.version, exc
                )

    policy = StepPolicy(deps=deps, run=run, step=step, ctx=ctx)
    recording_hooks = _RecordingHooks(deps, run, step, ctx)

    brief = build_brief(step, ltp_excerpt, digest, lessons_and_gotchas or [])

    session_id = f"{run.run_id}.{step.step_id}"
    session_manager = _build_session_manager(deps, session_id)

    agent = Agent(
        model=deps.model_factory("executor"),
        tools=[*core_tools, *selected_agent_tools, *sandbox_tools],
        system_prompt="You are the PortPilot step executor. Follow the brief; call complete_step when done.",
        conversation_manager=_build_conversation_manager(deps, run, step),
        session_manager=session_manager,
        interventions=[policy],
        hooks=[recording_hooks],
        plugins=_build_plugins(deps),
    )
    ctx._agent_ref = agent

    turns = 0
    deadline = time.monotonic() + step.budget.max_minutes * 60
    try:
        agent(brief)
        while not ctx.step_complete and turns < max_nudges:
            if time.monotonic() > deadline:
                logger.warning(
                    "step %s exceeded its wall-clock budget (%s min) without completing; stopping",
                    step.step_id,
                    step.budget.max_minutes,
                )
                deps.run_store.log_event(
                    run.run_id,
                    "budget_exceeded",
                    step.step_id,
                    {
                        "budget": "max_minutes",
                        "used": step.budget.max_minutes,
                        "limit": step.budget.max_minutes,
                    },
                )
                break
            turns += 1
            agent(CONTINUE_NUDGE)
    except (BudgetExceeded, LeaseLost):
        pass
    except Exception as exc:
        # (like BudgetExceeded/LeaseLost raised from StepPolicy.before_tool_call, or from
        # our own hooks) in EventLoopException; unwrap it so those two are still treated
        # as a clean step stop rather than an uncaught crash. Anything else re-raises.
        cause = exc.__cause__ or getattr(exc, "original_exception", None)
        if isinstance(cause, (BudgetExceeded, LeaseLost)):
            logger.info("step %s stopped: %s", step.step_id, cause)
        else:
            raise
    finally:
        totals = agent.event_loop_metrics.accumulated_usage
        step.usage.input_tokens = totals.get("inputTokens", 0)
        step.usage.output_tokens = totals.get("outputTokens", 0)
        step.usage.model_calls = turns + 1
        step.usage.tool_calls = recording_hooks.usage.tool_calls
        run.usage.add(step.usage)
        deps.run_store.update_run(run.run_id, usage=run.usage)
        deps.run_store.update_step(step.step_id, usage=step.usage)

    for name, helped in ctx.tools_used.items():
        for pick in step.selected_tools:
            if pick.name == name:
                pick.used = True
                pick.helpful = helped
    if step.selected_tools:
        deps.run_store.update_step(step.step_id, selected_tools=step.selected_tools)

    return step


__all__ = ["BRIEF_TOKEN_CAP", "CONTINUE_NUDGE", "build_brief", "execute_step"]
