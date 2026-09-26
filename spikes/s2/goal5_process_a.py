"""Goal 5, part 1: Process A runs a few turns incl. one tool call, then exits."""

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

    r1 = agent("Use remember_fact to store 'the launch code is PORT-42'. Confirm briefly.")
    r2 = agent(
        "What number did you just store, in the fact you remembered? Answer with just the number."
    )

    print(
        json.dumps(
            {
                "process": "A",
                "session_id": SESSION_ID,
                "agent_id": AGENT_ID,
                "message_count_after_A": len(agent.messages),
                "r1": str(r1).strip(),
                "r2": str(r2).strip(),
            },
            indent=2,
        )
    )
    repo.close()


if __name__ == "__main__":
    main()
