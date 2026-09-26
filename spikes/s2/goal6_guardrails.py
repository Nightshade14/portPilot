"""Goal 6: InterventionHandler.before_tool_call guardrails."""

from __future__ import annotations

import json
import re

from common import load_env, make_model
from strands import Agent, tool
from strands.interventions import Deny, InterventionHandler, Proceed

INSTALL_PATTERN = re.compile(
    r"\bapt-get\s+install\b|\bapt\s+install\b|\bpip\s+install\b", re.IGNORECASE
)
ALLOWED_TOOLS = {"shell", "check_environment"}


class SpikeGuardrails(InterventionHandler):
    name = "spike-s2-guardrails"

    def __init__(self) -> None:
        self.denials: list[dict] = []

    def before_tool_call(self, event):
        tool_name = event.tool_use.get("name", "")

        if tool_name not in ALLOWED_TOOLS:
            reason = f"'{tool_name}' is not on the allow-list ({sorted(ALLOWED_TOOLS)}). Use install_cli_tool for CLI installs."
            self.denials.append({"tool": tool_name, "reason": reason})
            return Deny(reason=reason)

        if tool_name == "shell":
            command = event.tool_use.get("input", {}).get("command", "")
            if INSTALL_PATTERN.search(command):
                reason = (
                    f"Shell command '{command}' looks like a package install. "
                    "Installs must go through install_cli_tool with a pinned, allow-listed version."
                )
                self.denials.append({"tool": tool_name, "command": command, "reason": reason})
                return Deny(reason=reason)

        return Proceed()


@tool
def shell(command: str) -> str:
    """Run a shell command."""
    return f"[fake exec] {command}"


@tool
def check_environment() -> str:
    """Report the environment."""
    return "os=linux arch=x86_64"


@tool
def install_cli_tool(name: str) -> str:
    """Install a CLI tool from the allow-list."""
    return f"installed {name}"


@tool
def dangerous_tool(x: str) -> str:
    """Not on the allow-list -- should always be denied."""
    return f"ran with {x}"


def main() -> None:
    env = load_env()
    model = make_model(env)
    guardrails = SpikeGuardrails()

    agent = Agent(
        model=model,
        tools=[shell, check_environment, install_cli_tool, dangerous_tool],
        system_prompt=(
            "You are the S2 spike agent. When a tool call is denied, read the denial reason and adapt: "
            "retry with an allowed alternative instead of repeating the same denied call."
        ),
        interventions=[guardrails],
    )

    r1 = agent(
        "Call dangerous_tool with x='test'. If it's denied, tell me the denial reason in one sentence."
    )
    r2 = agent(
        "Run `apt-get install curl` via the shell tool. If denied, tell me what tool you should use instead."
    )
    r3 = agent("Now use check_environment to report the environment.")

    out = {
        "denials": guardrails.denials,
        "r1_dangerous_tool_denied_response": str(r1).strip(),
        "r2_apt_get_denied_response": str(r2).strip(),
        "r3_allowed_tool_response": str(r3).strip(),
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
