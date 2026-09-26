"""Goal 5: AtlasSessionRepository (pymongo-backed SessionRepository) + RepositorySessionManager.

Collections used, in db `portpilot_spike_s2`:
  - sessions   {_id: session_id, ...Session.to_dict()}
  - agents     {_id: f"{session_id}::{agent_id}", session_id, agent_id, ...SessionAgent.to_dict()}
  - messages   {_id: f"{session_id}::{agent_id}::{message_id}", session_id, agent_id, message_id, ...}
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

MONGO_URI = "mongodb://127.0.0.1:27018/?directConnection=true"
DB_NAME = "portpilot_spike_s2"


class AtlasSessionRepository(SessionRepository):
    """pymongo-backed SessionRepository (stands in for a real Atlas repository)."""

    def __init__(self, client: MongoClient | None = None, db_name: str = DB_NAME) -> None:
        self._client = client or MongoClient(MONGO_URI)
        self._db = self._client[db_name]
        self.sessions: Collection = self._db["sessions"]
        self.agents: Collection = self._db["agents"]
        self.messages: Collection = self._db["messages"]

    # -- Session --------------------------------------------------------

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        doc = session.to_dict()
        doc["_id"] = session.session_id
        self.sessions.replace_one({"_id": session.session_id}, doc, upsert=True)
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        doc = self.sessions.find_one({"_id": session_id})
        if doc is None:
            return None
        doc.pop("_id", None)
        return Session.from_dict(doc)

    # -- Agent ------------------------------------------------------------

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        doc = session_agent.to_dict()
        doc["_id"] = f"{session_id}::{session_agent.agent_id}"
        doc["session_id"] = session_id
        self.agents.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        doc = self.agents.find_one({"_id": f"{session_id}::{agent_id}"})
        if doc is None:
            return None
        doc.pop("_id", None)
        doc.pop("session_id", None)
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
            results.append(SessionMessage.from_dict(doc))
        return results

    def drop_database(self) -> None:
        self._client.drop_database(self._db.name)

    def close(self) -> None:
        self._client.close()
