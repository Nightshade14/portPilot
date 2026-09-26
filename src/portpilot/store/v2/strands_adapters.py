"""Strands SDK adapters over Atlas. Owner: Lane M.

AtlasSessionRepository: productionized from the S2 spike
(`spikes/s2/atlas_session_repository.py`), on collections `agent_sessions`,
`agent_agents`, `agent_messages`, with a TTL on `expire_at`. Uses a synchronous
`pymongo.MongoClient` -- the spike's own choice, kept here: Strands session-repository
calls happen inside sync `Agent`/session-manager code (including from worker threads),
so a sync client avoids re-entering the shared loop thread from callbacks that may
already be running on it.

AtlasStorage: the Strands `strands.storage.Storage` protocol (async: write/read/delete/
list/search) for the `ContextOffloader` plugin, on collection `offload`. This one is
genuinely async (the protocol is `async def`), so it shares the run store's loop-thread
client rather than opening a second one -- pass either an `AtlasRunStore` (reuses its
loop + client) or a raw `uri`/`db_name` pair (opens its own loop-thread client, closed
via `close()`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ASCENDING, AsyncMongoClient, MongoClient
from pymongo.collection import Collection
from strands.session.session_repository import SessionRepository
from strands.storage.search.keyword import KeywordSearchStrategy
from strands.storage.storage import StorageSearchResult
from strands.types.session import Session, SessionAgent, SessionMessage

_SESSION_TTL_DAYS = 14
_WORD = re.compile(r"[a-z0-9]+")


class AtlasSessionRepository(SessionRepository):
    """pymongo-backed SessionRepository. Sync client (see module docstring).

    Collections, in `db_name`:
      - agent_sessions {_id: session_id, ...Session.to_dict(), expire_at}
      - agent_agents   {_id: f"{session_id}::{agent_id}", session_id, agent_id, ...}
      - agent_messages {_id: f"{session_id}::{agent_id}::{message_id}", session_id,
                         agent_id, message_id, ...}
    """

    def __init__(
        self,
        uri: str | None = None,
        db_name: str = "portpilot_mvp",
        *,
        client: MongoClient | None = None,
        ttl_days: int = _SESSION_TTL_DAYS,
    ) -> None:
        if client is None and uri is None:
            raise ValueError("AtlasSessionRepository requires either uri= or client=")
        self._client = client or MongoClient(uri, tz_aware=True, tzinfo=UTC)
        self._db = self._client[db_name]
        self._ttl_days = ttl_days
        self.sessions: Collection = self._db["agent_sessions"]
        self.agents: Collection = self._db["agent_agents"]
        self.messages: Collection = self._db["agent_messages"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.sessions.create_index(
            "expire_at",
            expireAfterSeconds=0,
            partialFilterExpression={"expire_at": {"$exists": True}},
        )
        self.agents.create_index("session_id")
        self.agents.create_index(
            "expire_at",
            expireAfterSeconds=0,
            partialFilterExpression={"expire_at": {"$exists": True}},
        )
        self.messages.create_index([("session_id", ASCENDING), ("agent_id", ASCENDING)])
        self.messages.create_index(
            "expire_at",
            expireAfterSeconds=0,
            partialFilterExpression={"expire_at": {"$exists": True}},
        )

    def _expire_at(self) -> datetime:
        return datetime.now(UTC) + timedelta(days=self._ttl_days)

    # -- Session --------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        doc = session.to_dict()
        doc["_id"] = session.session_id
        doc["expire_at"] = self._expire_at()
        self.sessions.replace_one({"_id": session.session_id}, doc, upsert=True)
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        doc = self.sessions.find_one({"_id": session_id})
        if doc is None:
            return None
        doc.pop("_id", None)
        doc.pop("expire_at", None)
        return Session.from_dict(doc)

    # -- Agent ------------------------------------------------------------

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        doc = session_agent.to_dict()
        doc["_id"] = f"{session_id}::{session_agent.agent_id}"
        doc["session_id"] = session_id
        doc["expire_at"] = self._expire_at()
        self.agents.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        doc = self.agents.find_one({"_id": f"{session_id}::{agent_id}"})
        if doc is None:
            return None
        doc.pop("_id", None)
        doc.pop("session_id", None)
        doc.pop("expire_at", None)
        return SessionAgent.from_dict(doc)

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        self.create_agent(session_id, session_agent)

    # -- Message ------------------------------------------------------------

    def _msg_id(self, session_id: str, agent_id: str, message_id: int) -> str:
        return f"{session_id}::{agent_id}::{message_id}"

    def create_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        doc = session_message.to_dict()
        doc["_id"] = self._msg_id(session_id, agent_id, session_message.message_id)
        doc["session_id"] = session_id
        doc["agent_id"] = agent_id
        doc["expire_at"] = self._expire_at()
        self.messages.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> SessionMessage | None:
        doc = self.messages.find_one({"_id": self._msg_id(session_id, agent_id, message_id)})
        if doc is None:
            return None
        doc.pop("_id", None)
        doc.pop("session_id", None)
        doc.pop("agent_id", None)
        doc.pop("expire_at", None)
        return SessionMessage.from_dict(doc)

    def update_message(
        self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any
    ) -> None:
        self.create_message(session_id, agent_id, session_message)

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        cursor = self.messages.find({"session_id": session_id, "agent_id": agent_id}).sort(
            "message_id", 1
        )
        cursor = cursor.skip(offset)
        if limit is not None:
            cursor = cursor.limit(limit)
        results = []
        for doc in cursor:
            doc.pop("_id", None)
            doc.pop("session_id", None)
            doc.pop("agent_id", None)
            doc.pop("expire_at", None)
            results.append(SessionMessage.from_dict(doc))
        return results

    def drop_database(self) -> None:
        """Test teardown only."""
        self._client.drop_database(self._db.name)

    def close(self) -> None:
        self._client.close()


class AtlasStorage:
    """Strands `Storage` protocol on collection `offload`. Genuinely async: every method
    is a coroutine called directly by Strands' own event loop (the `ContextOffloader`
    plugin), so this needs no `_LoopThread` wrapping of its own -- unlike `AtlasRunStore`/
    `AtlasToolStore`, which exist to give a *synchronous* protocol to sync callers.

    Documents: {_id: key, data: bytes, expire_at}. `search` uses the SDK's default
    keyword-overlap strategy (`KeywordSearchStrategy`) over `list()`, same as the base
    Protocol's default -- this backend has no richer index to offer.

    Pass either `run_store=` (an `AtlasRunStore`) to reuse its database and connection
    pool, or `client=`/`db_name=` for a standalone `AsyncMongoClient` this instance owns
    (call `await storage.init()` once, and `await storage.close()` when done -- both are
    no-ops when sharing a run_store, which owns that lifecycle itself).
    """

    def __init__(
        self,
        run_store: Any | None = None,
        *,
        client: AsyncMongoClient | None = None,
        db_name: str = "portpilot_mvp",
        ttl_days: int = _SESSION_TTL_DAYS,
    ) -> None:
        if run_store is None and client is None:
            raise ValueError("AtlasStorage requires either run_store= or client=")
        self._ttl_days = ttl_days
        self._owns_client = run_store is None
        if run_store is not None:
            self._col = run_store.async_store.db["offload"]
        else:
            self._client = client
            self._col = client[db_name]["offload"]

    async def init(self) -> AtlasStorage:
        """Create the TTL index (idempotent). No-op benefit when sharing a run_store,
        which already indexes its own collections in its own `init()` -- call this one
        too if `offload` is fresh, since `AtlasRunStore.init()` does not know about it."""
        await self._col.create_index(
            "expire_at",
            expireAfterSeconds=0,
            partialFilterExpression={"expire_at": {"$exists": True}},
        )
        return self

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def write(self, key: str, data: bytes) -> None:
        expire_at = datetime.now(UTC) + timedelta(days=self._ttl_days)
        await self._col.replace_one(
            {"_id": key}, {"_id": key, "data": data, "expire_at": expire_at}, upsert=True
        )

    async def read(self, key: str) -> bytes | None:
        doc = await self._col.find_one({"_id": key})
        if doc is None:
            return None
        return bytes(doc["data"])

    async def delete(self, key: str) -> None:
        await self._col.delete_one({"_id": key})

    async def list(self, query: str = "") -> list[str]:
        cursor = self._col.find({"_id": {"$regex": f"^{re.escape(query)}"}}, {"_id": 1}).sort(
            "_id", 1
        )
        return [doc["_id"] async for doc in cursor]

    async def search(self, query: str) -> list[StorageSearchResult]:
        return await KeywordSearchStrategy().search(self, query)


__all__ = ["AtlasSessionRepository", "AtlasStorage"]
