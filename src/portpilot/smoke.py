"""Lead's connectivity smoke tests (plan section 5, 0:00-0:20).

uv run portpilot smoke atlas
uv run portpilot smoke llm
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from portpilot.config import load_settings


def atlas_roundtrip() -> str:
    import asyncio

    from pymongo import AsyncMongoClient

    s = load_settings()
    if not s.mongodb_uri:
        raise SystemExit("MONGODB_URI is not set (see .env.example)")

    async def _roundtrip() -> bool:
        client: AsyncMongoClient = AsyncMongoClient(s.mongodb_uri, serverSelectionTimeoutMS=8000)
        try:
            coll = client[s.mongodb_db]["smoke"]
            token = uuid.uuid4().hex
            await coll.insert_one({"_id": token, "ts": datetime.now(UTC)})
            found = await coll.find_one({"_id": token})
            await coll.delete_one({"_id": token})
            return found is not None
        finally:
            await client.close()

    if not asyncio.run(_roundtrip()):
        raise SystemExit("Atlas: wrote a document but could not read it back")
    return f"Atlas OK (async pymongo): round-tripped one document in {s.mongodb_db}.smoke"


def llm_tool_call() -> str:
    from strands import Agent, tool

    from portpilot.harness.agent import build_model

    s = load_settings()
    calls: list[int] = []

    @tool
    def add(a: int, b: int) -> int:
        """Add two integers.

        Args:
            a: First integer.
            b: Second integer.
        """
        calls.append(a + b)
        return a + b

    agent = Agent(
        model=build_model(s),
        tools=[add],
        system_prompt="You must use the add tool for arithmetic. Reply with the number only.",
        callback_handler=None,
    )
    reply = agent("What is 19 + 23?")
    if calls != [42]:
        raise SystemExit(f"LLM: tool not called correctly (calls={calls}); try another MODEL_ID")
    return f"LLM OK: {s.model_id} called the tool once -> {calls[0]}; reply={str(reply).strip()!r}"
