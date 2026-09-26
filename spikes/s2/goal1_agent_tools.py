"""Goal 1: agent per STP, runtime tool registration, custom AgentTool."""

from __future__ import annotations

import asyncio
import json

from common import load_env, make_model
from strands import Agent, tool
from strands.types.tools import AgentTool, ToolGenerator, ToolSpec, ToolUse


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


class SandboxScriptTool(AgentTool):
    """Minimal custom AgentTool: pretends to run a script in a sandbox."""

    def __init__(self) -> None:
        super().__init__()
        self._tool_name = "run_sandbox_script"
        self._tool_spec: ToolSpec = {
            "name": self._tool_name,
            "description": "Run a script inside the STP sandbox and return its stdout.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "Shell script to run"},
                    },
                    "required": ["script"],
                }
            },
        }

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def tool_spec(self) -> ToolSpec:
        return self._tool_spec

    @property
    def tool_type(self) -> str:
        return "sandbox_script"

    async def stream(self, tool_use: ToolUse, invocation_state: dict, **kwargs) -> ToolGenerator:
        script = tool_use["input"].get("script", "")
        # Fake subprocess call -- a real DockerSandbox would exec this instead.
        fake_stdout = f"[fake-sandbox] ran: {script!r} -> exit 0\n"
        yield {
            "toolUseId": tool_use["toolUseId"],
            "status": "success",
            "content": [{"text": fake_stdout}],
        }


async def part_a_runtime_registration(env: dict[str, str]) -> dict:
    """Build a 2-tool agent, register a 3rd tool mid-session, confirm it's callable."""
    model = make_model(env)
    agent = Agent(
        model=model,
        tools=[add, multiply],
        system_prompt="You are a terse calculator. Use tools for all arithmetic.",
    )

    r1 = agent("What is 4 plus 5? Use the add tool.")
    used_before = _tool_names_used(r1)

    # Register a third tool at runtime through the public registry path.
    agent.tool_registry.register_dynamic_tool(subtract)

    r2 = agent("Now what is 10 minus 3? Use the subtract tool.")
    used_after = _tool_names_used(r2)

    return {
        "used_before_registration": used_before,
        "used_after_registration": used_after,
        "subtract_available_dynamic_tools": list(agent.tool_registry.dynamic_tools.keys()),
    }


async def part_b_custom_agent_tool(env: dict[str, str]) -> dict:
    """Instantiate SandboxScriptTool, hand it to a fresh agent, confirm round-trip."""
    model = make_model(env)
    tool_instance = SandboxScriptTool()
    agent = Agent(
        model=model,
        tools=[tool_instance],
        system_prompt="You must call run_sandbox_script for any request to run a script, then report its stdout verbatim.",
    )
    result = agent(
        "Run the script `echo hello` in the sandbox and tell me exactly what stdout was."
    )
    used = _tool_names_used(result)
    return {
        "tool_name": tool_instance.tool_name,
        "tool_type": tool_instance.tool_type,
        "used_tools": used,
        "final_text": str(result),
    }


async def part_c_fresh_agent_per_step(env: dict[str, str]) -> dict:
    """Confirm building a fresh Agent per step with a different tool set works cleanly."""
    model = make_model(env)
    step1 = Agent(model=model, tools=[add], system_prompt="Terse calculator.")
    r1 = step1("Add 2 and 2 using the tool.")

    step2 = Agent(model=model, tools=[multiply], system_prompt="Terse calculator.")
    r2 = step2("Multiply 6 and 7 using the tool.")

    return {
        "step1_tools": step1.tool_names,
        "step1_used": _tool_names_used(r1),
        "step2_tools": step2.tool_names,
        "step2_used": _tool_names_used(r2),
        "distinct_registries": id(step1.tool_registry) != id(step2.tool_registry),
    }


def _tool_names_used(result) -> list[str]:
    """Tool names the model actually invoked, from EventLoopMetrics.tool_metrics."""
    tool_metrics = getattr(result.metrics, "tool_metrics", None) or {}
    return list(tool_metrics.keys())


async def main() -> None:
    env = load_env()
    out = {}
    out["part_a_runtime_registration"] = await part_a_runtime_registration(env)
    out["part_b_custom_agent_tool"] = await part_b_custom_agent_tool(env)
    out["part_c_fresh_agent_per_step"] = await part_c_fresh_agent_per_step(env)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
