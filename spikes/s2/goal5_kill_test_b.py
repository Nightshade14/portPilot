"""Goal 5, part 3: Process B restores after A was kill -9'd mid-tool-call."""

from __future__ import annotations

import json

from atlas_session_repository import AtlasSessionRepository
from common import load_env, make_model
from strands import Agent, tool
from strands.session.repository_session_manager import RepositorySessionManager

SESSION_ID = "s2-goal5-kill"
AGENT_ID = "spike-agent"


@tool
def slow_tool(seconds: int = 30) -> str:
    """Sleep for the given number of seconds, then return."""
    import time

    time.sleep(seconds)
    return "done sleeping"


def main() -> None:
    env = load_env()
    model = make_model(env)
    repo = AtlasSessionRepository()
    session_manager = RepositorySessionManager(session_id=SESSION_ID, session_repository=repo)

    messages_before_restore = repo.list_messages(SESSION_ID, AGENT_ID)
    raw_before = [m.to_message() for m in messages_before_restore]

    agent = Agent(
        model=model,
        tools=[slow_tool],
        agent_id=AGENT_ID,
        system_prompt="You are a terse assistant. Always call slow_tool when asked to wait.",
        session_manager=session_manager,
    )

    restored_messages = list(agent.messages)
    dangling_tool_use = None
    for msg in restored_messages:
        for block in msg.get("content", []):
            if "toolUse" in block:
                dangling_tool_use = block["toolUse"]

    # Try one more turn to see if the agent loop tolerates the dangling call.
    r = agent("Did slow_tool finish? If not, just say 'not finished' briefly.")

    print(
        json.dumps(
            {
                "raw_messages_before_restore": raw_before,
                "restored_message_count": len(restored_messages),
                "restored_messages": restored_messages,
                "dangling_tool_use_found": dangling_tool_use,
                "post_restore_response": str(r).strip(),
            },
            indent=2,
            default=str,
        )
    )
    repo.close()


if __name__ == "__main__":
    main()
