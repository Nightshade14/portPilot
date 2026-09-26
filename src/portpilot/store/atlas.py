"""Atlas persistence on pymongo's native async API (AsyncMongoClient). Owner: Lane B.

Collections: migration_runs, milestones, artifacts, policies, events.
Indexes: run_id on each run-scoped collection; unique (name, version) on
policies; (run_id, ts) on events.

Two classes:

- AsyncAtlasStore: every Store method as a coroutine. Use it directly from
  async code (e.g. a future FastAPI view). Call `await store.init()` once.
- AtlasStore: the synchronous Store the harness uses. It owns one private
  event loop on a daemon thread and runs every AsyncAtlasStore call there.
  A private loop (rather than asyncio.run per call) keeps one client and one
  connection pool alive, and works even when the caller is itself inside a
  running event loop, which Strands tool calls can be.

Documents map 1:1 to the store contract; the Mongo `_id` is never exposed.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, TypeVar

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from portpilot.models import ArtifactKind, Milestone, Policy, PolicyStatus
from portpilot.store.base import NotFound, StoreError

T = TypeVar("T")

_POLICY_FIELDS = tuple(Policy.__dataclass_fields__)
_ORDER = [("created_at", ASCENDING), ("_id", ASCENDING)]


def _now() -> datetime:
    return datetime.now(UTC)


def _run_id() -> str:
    return f"run_{secrets.token_hex(6)}"


def _art_id() -> str:
    return f"art_{secrets.token_hex(6)}"


def _as_utc(value: Any) -> Any:
    """Ensure datetimes carry tzinfo even if the client handed back a naive value."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _clean(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    for key, value in doc.items():
        doc[key] = _as_utc(value)
    return doc


def _policy_from_doc(doc: dict[str, Any]) -> Policy:
    return Policy(**{k: doc[k] for k in _POLICY_FIELDS if k in doc})


class AsyncAtlasStore:
    def __init__(self, uri: str, db_name: str = "portpilot") -> None:
        self.client: AsyncMongoClient = AsyncMongoClient(
            uri, serverSelectionTimeoutMS=8000, tz_aware=True, tzinfo=UTC
        )
        self.db = self.client[db_name]
        self.runs = self.db["migration_runs"]
        self.milestones = self.db["milestones"]
        self.arts = self.db["artifacts"]
        self.policies = self.db["policies"]
        self.evts = self.db["events"]

    async def init(self) -> AsyncAtlasStore:
        """Create indexes (idempotent). Call once before use."""
        await self.runs.create_index([("run_id", ASCENDING)], unique=True)
        await self.milestones.create_index([("run_id", ASCENDING)])
        await self.arts.create_index([("run_id", ASCENDING)])
        await self.arts.create_index([("artifact_id", ASCENDING)], unique=True)
        await self.policies.create_index([("name", ASCENDING), ("version", ASCENDING)], unique=True)
        await self.evts.create_index([("run_id", ASCENDING)])
        await self.evts.create_index([("run_id", ASCENDING), ("ts", ASCENDING)])
        return self

    async def close(self) -> None:
        await self.client.close()

    async def drop(self) -> None:
        """Drop this store's database (test teardown only)."""
        await self.client.drop_database(self.db.name)

    async def _require_run(self, run_id: str) -> None:
        if await self.runs.find_one({"run_id": run_id}, {"_id": 1}) is None:
            raise NotFound(f"run {run_id!r} not found")

    # --- runs -----------------------------------------------------------
    async def create_run(self, source_path: str, policy_version: int) -> str:
        run_id = _run_id()
        now = _now()
        await self.runs.insert_one(
            {
                "run_id": run_id,
                "source_path": source_path,
                "policy_version": policy_version,
                "status": "running",
                "current_milestone": None,
                "attempt": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        return run_id

    async def get_run(self, run_id: str) -> dict[str, Any]:
        doc = await self.runs.find_one({"run_id": run_id})
        if doc is None:
            raise NotFound(f"run {run_id!r} not found")
        return _clean(doc)  # type: ignore[return-value]

    async def update_run(self, run_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        result = await self.runs.update_one({"run_id": run_id}, {"$set": fields})
        if result.matched_count == 0:
            raise NotFound(f"run {run_id!r} not found")

    # --- milestones -----------------------------------------------------
    async def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None:
        await self._require_run(run_id)
        await self.milestones.insert_one(
            {
                "run_id": run_id,
                "name": name,
                "attempt": attempt,
                "status": "started",
                "started_at": _now(),
                "completed_at": None,
                "artifact_ids": [],
            }
        )
        await self.runs.update_one(
            {"run_id": run_id},
            {"$set": {"current_milestone": name, "updated_at": _now()}},
        )

    async def complete_milestone(
        self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]
    ) -> None:
        await self._require_run(run_id)
        completed_seq = await self.milestones.count_documents(
            {"run_id": run_id, "status": "completed"}
        )
        completion = {
            "status": "completed",
            "completed_at": _now(),
            "artifact_ids": list(artifact_ids),
            "_completed_seq": completed_seq,
        }
        result = await self.milestones.update_one(
            {"run_id": run_id, "name": name, "attempt": attempt, "status": "started"},
            {"$set": completion},
        )
        if result.matched_count == 0:
            await self.milestones.insert_one(
                {"run_id": run_id, "name": name, "attempt": attempt, "started_at": None}
                | completion
            )

    async def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]:
        cursor = self.milestones.find({"run_id": run_id, "status": "completed"}).sort(
            [("completed_at", ASCENDING), ("_completed_seq", ASCENDING)]
        )
        return [(doc["name"], doc["attempt"]) async for doc in cursor]

    # --- artifacts ------------------------------------------------------
    async def put_artifact(
        self, run_id: str, kind: ArtifactKind, attempt: int, content: dict[str, Any]
    ) -> str:
        await self._require_run(run_id)
        artifact_id = _art_id()
        await self.arts.insert_one(
            {
                "artifact_id": artifact_id,
                "run_id": run_id,
                "kind": kind,
                "attempt": attempt,
                "content": content,
                "created_at": _now(),
            }
        )
        return artifact_id

    async def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        doc = await self.arts.find_one({"artifact_id": artifact_id})
        if doc is None:
            raise NotFound(f"artifact {artifact_id!r} not found")
        return _clean(doc)  # type: ignore[return-value]

    async def latest_artifact(self, run_id: str, kind: ArtifactKind) -> dict[str, Any] | None:
        # Newest first, one document: the reverse of the ascending contract order.
        cursor = (
            self.arts.find({"run_id": run_id, "kind": kind})
            .sort([("created_at", -1), ("_id", -1)])
            .limit(1)
        )
        docs = await cursor.to_list(length=1)
        return _clean(docs[0]) if docs else None

    async def artifacts(
        self, run_id: str, kind: ArtifactKind | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"run_id": run_id}
        if kind is not None:
            query["kind"] = kind
        if attempt is not None:
            query["attempt"] = attempt
        cursor = self.arts.find(query).sort(_ORDER)
        return [_clean(doc) async for doc in cursor]  # type: ignore[misc]

    # --- policies -------------------------------------------------------
    async def get_policy(self, name: str, version: int | None = None) -> Policy:
        if version is None:
            doc = await self.policies.find_one({"name": name, "status": "active"})
            if doc is None:
                raise NotFound(f"no active policy named {name!r}")
            return _policy_from_doc(doc)
        doc = await self.policies.find_one({"name": name, "version": version})
        if doc is None:
            raise NotFound(f"policy {name!r} v{version} not found")
        return _policy_from_doc(doc)

    async def list_policies(self, name: str) -> list[Policy]:
        cursor = self.policies.find({"name": name}).sort("version", ASCENDING)
        return [_policy_from_doc(doc) async for doc in cursor]

    async def save_policy(self, policy: Policy) -> None:
        try:
            await self.policies.insert_one(policy.to_doc())
        except DuplicateKeyError as exc:
            raise StoreError(f"policy {policy.name!r} v{policy.version} already exists") from exc

    async def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None:
        result = await self.policies.update_one(
            {"name": name, "version": version},
            {"$set": {"status": status, "decision": decision}},
        )
        if result.matched_count == 0:
            raise NotFound(f"policy {name!r} v{version} not found")

    # --- events ---------------------------------------------------------
    async def log_event(
        self, run_id: str, type: str, milestone: str, payload: dict[str, Any]
    ) -> None:
        seq = await self.evts.count_documents({"run_id": run_id})
        await self.evts.insert_one(
            {
                "run_id": run_id,
                "type": type,
                "milestone": milestone,
                "payload": payload,
                "ts": _now(),
                "seq": seq,
            }
        )

    async def events(self, run_id: str) -> list[dict[str, Any]]:
        cursor = self.evts.find({"run_id": run_id}).sort([("ts", ASCENDING), ("seq", ASCENDING)])
        return [_clean(doc) async for doc in cursor]  # type: ignore[misc]


class _LoopThread:
    """One private asyncio loop on a daemon thread; run coroutines on it from sync code."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self.loop.run_forever, name="portpilot-atlas-loop", daemon=True
        )
        self._thread.start()

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def stop(self) -> None:
        async def _cancel_pending() -> None:
            current = asyncio.current_task()
            for task in asyncio.all_tasks():
                if task is not current:
                    task.cancel()

        try:
            self.run(_cancel_pending())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=5)
            self.loop.close()


class AtlasStore:
    """Synchronous Store over AsyncAtlasStore (see module docstring)."""

    def __init__(self, uri: str, db_name: str = "portpilot") -> None:
        self._loop = _LoopThread()

        async def _create() -> AsyncAtlasStore:
            # Created on the loop thread so the client binds to that loop.
            return AsyncAtlasStore(uri, db_name)

        self._async = self._loop.run(_create())
        try:
            self._loop.run(self._async.init())
        except Exception:
            self.close()
            raise

    @property
    def async_store(self) -> AsyncAtlasStore:
        return self._async

    def close(self) -> None:
        try:
            self._loop.run(self._async.close())
        finally:
            self._loop.stop()

    def drop(self) -> None:
        self._loop.run(self._async.drop())

    def create_run(self, source_path: str, policy_version: int) -> str:
        return self._loop.run(self._async.create_run(source_path, policy_version))

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._loop.run(self._async.get_run(run_id))

    def update_run(self, run_id: str, **fields: Any) -> None:
        self._loop.run(self._async.update_run(run_id, **fields))

    def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None:
        self._loop.run(self._async.start_milestone(run_id, name, attempt))

    def complete_milestone(
        self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]
    ) -> None:
        self._loop.run(self._async.complete_milestone(run_id, name, attempt, artifact_ids))

    def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]:
        return self._loop.run(self._async.completed_milestones(run_id))

    def put_artifact(
        self, run_id: str, kind: ArtifactKind, attempt: int, content: dict[str, Any]
    ) -> str:
        return self._loop.run(self._async.put_artifact(run_id, kind, attempt, content))

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        return self._loop.run(self._async.get_artifact(artifact_id))

    def latest_artifact(self, run_id: str, kind: ArtifactKind) -> dict[str, Any] | None:
        return self._loop.run(self._async.latest_artifact(run_id, kind))

    def artifacts(
        self, run_id: str, kind: ArtifactKind | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        return self._loop.run(self._async.artifacts(run_id, kind, attempt))

    def get_policy(self, name: str, version: int | None = None) -> Policy:
        return self._loop.run(self._async.get_policy(name, version))

    def list_policies(self, name: str) -> list[Policy]:
        return self._loop.run(self._async.list_policies(name))

    def save_policy(self, policy: Policy) -> None:
        self._loop.run(self._async.save_policy(policy))

    def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None:
        self._loop.run(self._async.set_policy_status(name, version, status, decision))

    def log_event(self, run_id: str, type: str, milestone: str, payload: dict[str, Any]) -> None:
        self._loop.run(self._async.log_event(run_id, type, milestone, payload))

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return self._loop.run(self._async.events(run_id))
