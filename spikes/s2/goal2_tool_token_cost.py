"""Goal 2: token cost of the ~11 core tool definitions vs 0 tools."""

from __future__ import annotations

import json

from common import load_env, make_model
from strands import Agent, tool


def _mk(name: str, desc: str):
    @tool(name=name, description=desc)
    def _t(query: str = "") -> str:
        return "ok"

    return _t


CORE_TOOL_SPECS = [
    ("shell", "Run a shell command inside the sandbox and return stdout/stderr/exit code."),
    ("file_editor", "View, create, or edit a file inside the sandbox workspace."),
    (
        "complete_step",
        "Mark the current STP as complete and hand off to the harness for verification.",
    ),
    (
        "search_knowledge",
        "Hybrid search over the knowledge collection for lessons, gotchas, and tool cards.",
    ),
    ("search_tools", "Search the tool registry for library tools matching a capability query."),
    ("load_tool", "Load a library tool by name and version into the current agent's tool set."),
    ("create_tool", "Save a new candidate tool with its schema, files, and tests."),
    (
        "check_environment",
        "Report OS, architecture, installed CLIs, free disk/memory, and detected languages.",
    ),
    ("install_cli_tool", "Install a CLI tool from the reviewed allow-list at a pinned version."),
    ("record_lesson", "Record a durable lesson learned during this run."),
    (
        "record_gotcha",
        "Record a gotcha (an API quirk or unexpected failure) encountered during this run.",
    ),
]


def main() -> None:
    env = load_env()
    model = make_model(env)
    prompt = "Say the word 'ready' and nothing else."

    agent_no_tools = Agent(model=model, tools=[], system_prompt="You are a terse assistant.")
    r0 = agent_no_tools(prompt)

    core_tools = [_mk(name, desc) for name, desc in CORE_TOOL_SPECS]
    agent_with_tools = Agent(
        model=model, tools=core_tools, system_prompt="You are a terse assistant."
    )
    r1 = agent_with_tools(prompt)

    u0 = r0.metrics.accumulated_usage
    u1 = r1.metrics.accumulated_usage

    out = {
        "num_tools": len(core_tools),
        "zero_tools_input_tokens": u0["inputTokens"],
        "eleven_tools_input_tokens": u1["inputTokens"],
        "delta_input_tokens": u1["inputTokens"] - u0["inputTokens"],
        "zero_tools_usage": dict(u0),
        "eleven_tools_usage": dict(u1),
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
