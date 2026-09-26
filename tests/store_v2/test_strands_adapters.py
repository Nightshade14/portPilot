"""Strands adapters tests (marker `mongo`): AtlasSessionRepository + AtlasStorage.

Uses a minimal scripted `strands.models.Model` subclass (no LLM) instead of the S2
spike's live-OpenRouter `make_model` helper, per the brief. It replays canned text/
tool-call turns from a fixed script, so the test is deterministic and free.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

import pytest
from strands import Agent, tool
from strands.models.model import Model
from strands.session.repository_session_manager import RepositorySessionManager
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

from portpilot.store.v2.strands_adapters import AtlasSessionRepository, AtlasStorage


class ScriptedModel(Model):
    """Replays a fixed sequence of turns: each is either plain text, or one tool call
    followed (on the *next* invocation, once the tool result comes back) by text.
    `turns` is a list of either {"text": str} or {"tool": {"name", "input", "text_after"}}.
    """

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        self._turns = iter(turns)
        self._config: dict[str, Any] = {}
        self._pending_after: str | None = None

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> Any:
        return self._config

    async def structured_output(self, *args: Any, **kwargs: Any):  # pragma: no cover - unused
        raise NotImplementedError

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        # If the last message is a tool result, we are the "text_after" continuation of
        # the most recently issued tool call; find it by scanning for a pending tool use.
        last = messages[-1] if messages else None
        if last and last.get("role") == "user":
            for block in last.get("content", []):
                if "toolResult" in block:
                    turn = self._pending_after
                    async for event in self._text_events(turn):
                        yield event
                    return

        turn = next(self._turns)
        if "tool" in turn:
            self._pending_after = turn["tool"].get("text_after", "done")
            async for event in self._tool_events(turn["tool"]):
                yield event
            return

        async for event in self._text_events(turn.get("text", "")):
            yield event

    async def _text_events(self, text: str) -> AsyncIterable[StreamEvent]:
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        }

    async def _tool_events(self, tool_call: dict[str, Any]) -> AsyncIterable[StreamEvent]:
        import json

        tool_use_id = "tool_" + tool_call["name"]
        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"name": tool_call["name"], "toolUseId": tool_use_id}},
            }
        }
        yield {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": json.dumps(tool_call["input"])}},
            }
        }
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        }


@tool
def remember_fact(fact: str) -> str:
    """Store a fact for later. Returns confirmation."""
    return f"stored: {fact}"


def _turns() -> list[dict[str, Any]]:
    return [
        {"tool": {"name": "remember_fact", "input": {"fact": "42"}, "text_after": "Stored 42."}},
        {"text": "42"},
    ]


@pytest.fixture
def session_repo(mongo_uri: str, mongo_db_name: str):
    repo = AtlasSessionRepository(uri=mongo_uri, db_name=mongo_db_name)
    try:
        yield repo
    finally:
        repo.drop_database()
        repo.close()


def test_atlas_session_repository_restores_identical_messages_in_new_agent(session_repo) -> None:
    session_id = "test-session"
    agent_id = "test-agent"

    manager_a = RepositorySessionManager(session_id=session_id, session_repository=session_repo)
    agent_a = Agent(
        model=ScriptedModel(_turns()),
        tools=[remember_fact],
        agent_id=agent_id,
        session_manager=manager_a,
    )
    agent_a("Remember 42.")
    agent_a("What did you store?")

    messages_after_a = list(agent_a.messages)
    assert (
        len(messages_after_a) >= 4
    )  # user, assistant tool-use, user tool-result, assistant text...

    manager_b = RepositorySessionManager(session_id=session_id, session_repository=session_repo)
    agent_b = Agent(
        model=ScriptedModel(_turns()),  # unused: no further turns are driven
        tools=[remember_fact],
        agent_id=agent_id,
        session_manager=manager_b,
    )

    assert agent_b.messages == messages_after_a


def test_atlas_storage_read_write_list_delete_search(mongo_uri: str, mongo_db_name: str) -> None:
    from pymongo import AsyncMongoClient

    async def _run() -> None:
        client: AsyncMongoClient = AsyncMongoClient(mongo_uri)
        try:
            storage = await AtlasStorage(client=client, db_name=mongo_db_name).init()

            assert await storage.read("offloader/a") is None

            await storage.write("offloader/a", b"the launch code is 42")
            await storage.write("offloader/b", b"unrelated content")

            assert await storage.read("offloader/a") == b"the launch code is 42"

            keys = await storage.list("offloader/")
            assert keys == ["offloader/a", "offloader/b"]

            results = await storage.search("launch code")
            assert results
            assert results[0].key == "offloader/a"

            await storage.delete("offloader/a")
            assert await storage.read("offloader/a") is None
            assert await storage.list("offloader/") == ["offloader/b"]
        finally:
            await client.drop_database(mongo_db_name)
            await client.close()

    import asyncio

    asyncio.run(_run())
