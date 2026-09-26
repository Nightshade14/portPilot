"""Goal 5, part 3: kill -9 mid-tool-call, then observe what Strands does on resume.

Run as: python goal5_kill_test_a.py &   (backgrounds, calls a tool that sleeps 30s)
Then, after grabbing its PID, `kill -9 <pid>` while it's inside the tool.
Then run goal5_kill_test_b.py to restore and see the dangling tool call.
"""

from __future__ import annotations

import os
import time

from atlas_session_repository import AtlasSessionRepository
from common import load_env, make_model
from strands import Agent, tool
from strands.session.repository_session_manager import RepositorySessionManager

SESSION_ID = "s2-goal5-kill"
AGENT_ID = "spike-agent"


@tool
def slow_tool(seconds: int = 30) -> str:
    """Sleep for the given number of seconds, then return."""
    print(f"[slow_tool] pid={os.getpid()} sleeping {seconds}s ...", flush=True)
    time.sleep(seconds)
    return "done sleeping"


def main() -> None:
    env = load_env()
    model = make_model(env)
    repo = AtlasSessionRepository()
    # Fresh session each run of part 3.
    repo.sessions.delete_many({"_id": SESSION_ID})
    repo.agents.delete_many({"session_id": SESSION_ID})
    repo.messages.delete_many({"session_id": SESSION_ID})

    session_manager = RepositorySessionManager(session_id=SESSION_ID, session_repository=repo)
    agent = Agent(
        model=model,
        tools=[slow_tool],
        agent_id=AGENT_ID,
        system_prompt="You are a terse assistant. Always call slow_tool when asked to wait.",
        session_manager=session_manager,
    )
    print(f"[process A] pid={os.getpid()}", flush=True)
    agent("Call slow_tool with seconds=30, then report what it returned.")
    print("[process A] finished normally (should not happen if killed mid-call)", flush=True)


if __name__ == "__main__":
    main()
