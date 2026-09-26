"""Goal 5, part 2: Process B restores the same session and continues coherently."""

from __future__ import annotations

import json

from atlas_session_repository import AtlasSessionRepository
from common import load_env, make_model
from strands import Agent, tool
from strands.session.repository_session_manager import RepositorySessionManager

SESSION_ID = "s2-goal5-durable"
AGENT_ID = "spike-agent"


@tool
def remember_fact(fact: str) -> str:
    """Store a fact for later. Returns confirmation."""
    return f"stored: {fact}"


def main() -> None:
    env = load_env()
    model = make_model(env)
    repo = AtlasSessionRepository()
    session_manager = RepositorySessionManager(session_id=SESSION_ID, session_repository=repo)

    agent = Agent(
        model=model,
        tools=[remember_fact],
        agent_id=AGENT_ID,
        system_prompt="You are a terse assistant for the S2 durable-session spike.",
        session_manager=session_manager,
    )

    message_count_on_restore = len(agent.messages)
    r3 = agent(
        "Without calling any tool, what number did I ask you to remember earlier in this conversation? "
        "Answer with just the number."
    )

    print(
        json.dumps(
            {
                "process": "B",
                "session_id": SESSION_ID,
                "message_count_on_restore": message_count_on_restore,
                "restored_first_message": agent.messages[0] if agent.messages else None,
                "r3": str(r3).strip(),
                "message_count_after_B": len(agent.messages),
            },
            indent=2,
            default=str,
        )
    )
    repo.close()


if __name__ == "__main__":
    main()
