"""Atlas persistence for RunStore / ToolStore (MVP_PLAN 3.7/4, core.interfaces). Owner: Lane M.

Async-client pattern reused from v0 `store/atlas.py`: an `Async*` class does the real
work as coroutines against `AsyncMongoClient`; a synchronous wrapper owns a private
event-loop thread (`_loop._LoopThread`) and exposes the `RunStore` / `ToolStore`
protocols the rest of the harness (running on worker threads) calls directly.

Errors: a Mongo `DuplicateKeyError` on a unique index becomes `core.interfaces.Conflict`;
a missing document raises `core.interfaces.NotFound`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from gridfs.asynchronous.grid_file import AsyncGridFSBucket
from pymongo import ASCENDING, AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from portpilot.core.interfaces import Conflict, NotFound
from portpilot.core.models import (
    LongTermPlan,
    Run,
    ShortTermPlan,
    ToolRecord,
    ToolStatus,
    new_id,
    utcnow,
)
from portpilot.store.v2._loop import _LoopThread

# JSON-able content whose serialized size exceeds this goes to GridFS.
_GRIDFS_THRESHOLD_BYTES = 1_000_000
# Terminal-status events/artifacts are given a TTL this far in the future.
_EVENT_TTL_DAYS = 14


def _as_utc(value: Any) -> Any:
    """Ensure datetimes carry tzinfo even if the client handed back a naive value."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _strip_id(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    for key, value in doc.items():
        doc[key] = _as_utc(value)
    return doc


class AsyncAtlasRunStore:
    """Coroutine implementation of `core.interfaces.RunStore` over AsyncMongoClient."""

    def __init__(self, uri: str, db_name: str) -> None:
        self.client: AsyncMongoClient = AsyncMongoClient(
            uri, serverSelectionTimeoutMS=8000, tz_aware=True, tzinfo=UTC
        )
        self.db = self.client[db_name]
        self.runs = self.db["migration_runs"]
        self.plans = self.db["plans"]
        self.steps = self.db["steps"]
        self.events = self.db["events"]
        self.artifacts = self.db["artifacts"]
        self._gridfs = AsyncGridFSBucket(self.db, bucket_name="artifacts_fs")

    async def init(self) -> AsyncAtlasRunStore:
        """Create indexes (idempotent). Call once before use."""
        await self.runs.create_index([("run_id", ASCENDING)], unique=True)
        await self.runs.create_index([("status", ASCENDING), ("lease.expires_at", ASCENDING)])
        await self.plans.create_index([("run_id", ASCENDING), ("version", ASCENDING)], unique=True)
        await self.steps.create_index([("step_id", ASCENDING)], unique=True)
        await self.steps.create_index([("run_id", ASCENDING), ("seq", ASCENDING)], unique=True)
        await self.events.create_index([("run_id", ASCENDING), ("seq", ASCENDING)], unique=True)
        await self.events.create_index(
            "expire_at",
            expireAfterSeconds=0,
            partialFilterExpression={"expire_at": {"$exists": True}},
        )
        await self.artifacts.create_index([("artifact_id", ASCENDING)], unique=True)
        await self.artifacts.create_index([("run_id", ASCENDING), ("kind", ASCENDING)])
        await self.artifacts.create_index(
            "expire_at",
            expireAfterSeconds=0,
            partialFilterExpression={"expire_at": {"$exists": True}},
        )
        return self

    async def close(self) -> None:
        await self.client.close()

    async def drop(self) -> None:
        """Drop this store's database (test teardown only)."""
        await self.client.drop_database(self.db.name)

    # ----------------------------------------------------------------- runs

    async def create_run(self, run: Run) -> str:
        doc = run.to_doc()
        try:
            await self.runs.insert_one(doc)
        except DuplicateKeyError as exc:
            raise Conflict(run.run_id) from exc
        return run.run_id

    async def get_run(self, run_id: str) -> Run:
        doc = await self.runs.find_one({"run_id": run_id})
        if doc is None:
            raise NotFound(run_id)
        return Run.from_doc(_strip_id(doc))

    async def list_runs(self, limit: int = 50) -> list[Run]:
        cursor = self.runs.find().sort("created_at", -1).limit(limit)
        return [Run.from_doc(_strip_id(doc)) async for doc in cursor]

    async def update_run(self, run_id: str, **fields: Any) -> None:
        payload = {k: _to_doc_value(v) for k, v in fields.items()}
        payload["updated_at"] = utcnow()
        result = await self.runs.update_one({"run_id": run_id}, {"$set": payload})
        if result.matched_count == 0:
            raise NotFound(run_id)
        status = fields.get("status")
        if status in ("completed", "failed", "cancelled"):
            expire_at = utcnow() + timedelta(days=_EVENT_TTL_DAYS)
            await self.events.update_many({"run_id": run_id}, {"$set": {"expire_at": expire_at}})

    async def claim_run(self, worker_id: str, lease_s: int = 60) -> Run | None:
        now = utcnow()
        doc = await self.runs.find_one_and_update(
            {
                "$or": [
                    {"status": "queued"},
                    {
                        "status": "running",
                        "$or": [{"lease": None}, {"lease.expires_at": {"$lt": now}}],
                    },
                ]
            },
            {
                "$set": {
                    "lease": {"owner": worker_id, "expires_at": now + timedelta(seconds=lease_s)},
                    "status": "running",
                    "updated_at": now,
                }
            },
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        return Run.from_doc(_strip_id(doc))

    async def heartbeat(self, run_id: str, worker_id: str, lease_s: int = 60) -> bool:
        now = utcnow()
        result = await self.runs.update_one(
            {"run_id": run_id, "lease.owner": worker_id},
            {
                "$set": {
                    "lease": {"owner": worker_id, "expires_at": now + timedelta(seconds=lease_s)}
                }
            },
        )
        return result.matched_count > 0

    async def release(self, run_id: str, worker_id: str) -> None:
        await self.runs.update_one(
            {"run_id": run_id, "lease.owner": worker_id}, {"$set": {"lease": None}}
        )

    # ---------------------------------------------------------------- plans

    async def save_plan(self, plan: LongTermPlan) -> None:
        try:
            await self.plans.insert_one(plan.to_doc())
        except DuplicateKeyError as exc:
            raise Conflict(f"{plan.run_id} v{plan.version}") from exc

    async def latest_plan(self, run_id: str) -> LongTermPlan | None:
        cursor = self.plans.find({"run_id": run_id}).sort("version", -1).limit(1)
        docs = await cursor.to_list(length=1)
        return LongTermPlan.from_doc(_strip_id(docs[0])) if docs else None

    # ---------------------------------------------------------------- steps

    async def save_step(self, step: ShortTermPlan) -> None:
        doc = step.to_doc()
        try:
            await self.steps.replace_one({"step_id": step.step_id}, doc, upsert=True)
        except DuplicateKeyError as exc:
            raise Conflict(f"{step.run_id} seq {step.seq}") from exc

    async def get_step(self, step_id: str) -> ShortTermPlan:
        doc = await self.steps.find_one({"step_id": step_id})
        if doc is None:
            raise NotFound(step_id)
        return ShortTermPlan.from_doc(_strip_id(doc))

    async def update_step(self, step_id: str, **fields: Any) -> None:
        payload = {k: _to_doc_value(v) for k, v in fields.items()}
        try:
            result = await self.steps.update_one({"step_id": step_id}, {"$set": payload})
        except DuplicateKeyError as exc:
            raise Conflict(step_id) from exc
        if result.matched_count == 0:
            raise NotFound(step_id)

    async def steps_for_run(self, run_id: str) -> list[ShortTermPlan]:
        cursor = self.steps.find({"run_id": run_id}).sort("seq", ASCENDING)
        return [ShortTermPlan.from_doc(_strip_id(doc)) async for doc in cursor]

    # --------------------------------------------------------------- events

    async def log_event(
        self, run_id: str, type: str, step_id: str | None = None, payload: dict | None = None
    ) -> int:
        counter = await self.runs.find_one_and_update(
            {"run_id": run_id},
            {"$inc": {"event_seq": 1}},
            return_document=ReturnDocument.AFTER,
            projection={"event_seq": 1},
        )
        if counter is None:
            raise NotFound(run_id)
        seq = counter["event_seq"]
        await self.events.insert_one(
            {
                "run_id": run_id,
                "seq": seq,
                "ts": utcnow(),
                "type": type,
                "step_id": step_id,
                "payload": payload or {},
            }
        )
        return seq

    async def events_for_run(
        self, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        cursor = (
            self.events.find({"run_id": run_id, "seq": {"$gt": after_seq}})
            .sort("seq", ASCENDING)
            .limit(limit)
        )
        out = []
        async for doc in cursor:
            doc.pop("_id", None)
            doc.pop("expire_at", None)
            out.append(doc)
        return out

    # ------------------------------------------------------------ artifacts

    async def put_artifact(
        self, run_id: str, step_id: str | None, kind: str, content: Any, name: str = ""
    ) -> str:
        artifact_id = new_id("art")
        raw = json.dumps(content, default=str).encode("utf-8")
        doc: dict[str, Any] = {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "step_id": step_id,
            "kind": kind,
            "name": name,
            "created_at": utcnow(),
        }
        if len(raw) > _GRIDFS_THRESHOLD_BYTES:
            gridfs_id = await self._gridfs.upload_from_stream(artifact_id, raw)
            doc["gridfs_id"] = gridfs_id
        else:
            doc["content"] = content
        await self.artifacts.insert_one(doc)
        return artifact_id

    async def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        doc = await self.artifacts.find_one({"artifact_id": artifact_id})
        if doc is None:
            raise NotFound(artifact_id)
        doc.pop("_id", None)
        doc.pop("expire_at", None)
        gridfs_id = doc.pop("gridfs_id", None)
        if gridfs_id is not None:
            stream = await self._gridfs.open_download_stream(gridfs_id)
            raw = await stream.read()
            doc["content"] = json.loads(raw.decode("utf-8"))
        return doc

    async def list_artifacts(self, run_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"run_id": run_id}
        if kind is not None:
            query["kind"] = kind
        cursor = self.artifacts.find(query, {"content": 0}).sort("created_at", ASCENDING)
        out = []
        async for doc in cursor:
            doc.pop("_id", None)
            doc.pop("expire_at", None)
            doc.pop("gridfs_id", None)
            out.append(doc)
        return out


def _to_doc_value(value: Any) -> Any:
    """Serialize a dataclass value passed to update_run/update_step, like `_Doc.to_doc`."""
    if hasattr(value, "to_doc"):
        return value.to_doc()
    if isinstance(value, list):
        return [_to_doc_value(v) for v in value]
    return value


class AtlasRunStore:
    """Synchronous `RunStore` over `AsyncAtlasRunStore` (see module docstring)."""

    def __init__(self, uri: str, db_name: str) -> None:
        self._loop = _LoopThread()

        async def _create() -> AsyncAtlasRunStore:
            return AsyncAtlasRunStore(uri, db_name)

        self._async = self._loop.run(_create())
        try:
            self._loop.run(self._async.init())
        except Exception:
            self.close()
            raise

    @property
    def async_store(self) -> AsyncAtlasRunStore:
        return self._async

    def close(self) -> None:
        try:
            self._loop.run(self._async.close())
        finally:
            self._loop.stop()

    def drop(self) -> None:
        self._loop.run(self._async.drop())

    def create_run(self, run: Run) -> str:
        return self._loop.run(self._async.create_run(run))

    def get_run(self, run_id: str) -> Run:
        return self._loop.run(self._async.get_run(run_id))

    def list_runs(self, limit: int = 50) -> list[Run]:
        return self._loop.run(self._async.list_runs(limit))

    def update_run(self, run_id: str, **fields: Any) -> None:
        self._loop.run(self._async.update_run(run_id, **fields))

    def claim_run(self, worker_id: str, lease_s: int = 60) -> Run | None:
        return self._loop.run(self._async.claim_run(worker_id, lease_s))

    def heartbeat(self, run_id: str, worker_id: str, lease_s: int = 60) -> bool:
        return self._loop.run(self._async.heartbeat(run_id, worker_id, lease_s))

    def release(self, run_id: str, worker_id: str) -> None:
        self._loop.run(self._async.release(run_id, worker_id))

    def save_plan(self, plan: LongTermPlan) -> None:
        self._loop.run(self._async.save_plan(plan))

    def latest_plan(self, run_id: str) -> LongTermPlan | None:
        return self._loop.run(self._async.latest_plan(run_id))

    def save_step(self, step: ShortTermPlan) -> None:
        self._loop.run(self._async.save_step(step))

    def get_step(self, step_id: str) -> ShortTermPlan:
        return self._loop.run(self._async.get_step(step_id))

    def update_step(self, step_id: str, **fields: Any) -> None:
        self._loop.run(self._async.update_step(step_id, **fields))

    def steps(self, run_id: str) -> list[ShortTermPlan]:
        return self._loop.run(self._async.steps_for_run(run_id))

    def log_event(
        self, run_id: str, type: str, step_id: str | None = None, payload: dict | None = None
    ) -> int:
        return self._loop.run(self._async.log_event(run_id, type, step_id, payload))

    def events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        return self._loop.run(self._async.events_for_run(run_id, after_seq, limit))

    def put_artifact(
        self, run_id: str, step_id: str | None, kind: str, content: Any, name: str = ""
    ) -> str:
        return self._loop.run(self._async.put_artifact(run_id, step_id, kind, content, name))

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        return self._loop.run(self._async.get_artifact(artifact_id))

    def list_artifacts(self, run_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        return self._loop.run(self._async.list_artifacts(run_id, kind))


class AsyncAtlasToolStore:
    """Coroutine implementation of `core.interfaces.ToolStore` over AsyncMongoClient."""

    def __init__(self, uri: str, db_name: str) -> None:
        self.client: AsyncMongoClient = AsyncMongoClient(
            uri, serverSelectionTimeoutMS=8000, tz_aware=True, tzinfo=UTC
        )
        self.db = self.client[db_name]
        self.tools = self.db["tools"]

    async def init(self) -> AsyncAtlasToolStore:
        await self.tools.create_index([("name", ASCENDING), ("version", ASCENDING)], unique=True)
        await self.tools.create_index("status")
        return self

    async def close(self) -> None:
        await self.client.close()

    async def drop(self) -> None:
        await self.client.drop_database(self.db.name)

    async def save(self, record: ToolRecord) -> None:
        try:
            await self.tools.insert_one(record.to_doc())
        except DuplicateKeyError as exc:
            raise Conflict(f"{record.name}@{record.version}") from exc

    async def get(self, name: str, version: int | None = None) -> ToolRecord:
        if version is None:
            cursor = (
                self.tools.find({"name": name, "status": "active"}).sort("version", -1).limit(1)
            )
            docs = await cursor.to_list(length=1)
            if not docs:
                raise NotFound(f"{name} (no active version)")
            return ToolRecord.from_doc(_strip_id(docs[0]))
        doc = await self.tools.find_one({"name": name, "version": version})
        if doc is None:
            raise NotFound(f"{name}@{version}")
        return ToolRecord.from_doc(_strip_id(doc))

    async def versions(self, name: str) -> list[ToolRecord]:
        cursor = self.tools.find({"name": name}).sort("version", ASCENDING)
        return [ToolRecord.from_doc(_strip_id(doc)) async for doc in cursor]

    async def list_tools(self, status: ToolStatus | None = None) -> list[ToolRecord]:
        """Latest version per name, among versions matching `status` when given (same
        filter-then-latest semantics as `core.fakes.InMemoryToolStore.list_tools`)."""
        query: dict[str, Any] = {} if status is None else {"status": status}
        pipeline: list[dict[str, Any]] = [
            {"$match": query},
            {"$sort": {"version": -1}},
            {"$group": {"_id": "$name", "doc": {"$first": "$$ROOT"}}},
        ]
        records = [
            ToolRecord.from_doc(_strip_id(row["doc"]))
            async for row in await self.tools.aggregate(pipeline)
        ]
        return sorted(records, key=lambda t: t.name)

    async def set_status(self, name: str, version: int, status: ToolStatus) -> None:
        result = await self.tools.update_one(
            {"name": name, "version": version}, {"$set": {"status": status}}
        )
        if result.matched_count == 0:
            raise NotFound(f"{name}@{version}")

    async def record_use(self, name: str, version: int, run_id: str, ok: bool) -> None:
        inc = {"stats.uses": 1, "stats.successes" if ok else "stats.failures": 1}
        result = await self.tools.update_one(
            {"name": name, "version": version},
            {"$inc": inc, "$addToSet": {"stats.runs_used_in": run_id}},
        )
        if result.matched_count == 0:
            raise NotFound(f"{name}@{version}")

    async def next_version(self, name: str) -> int:
        cursor = self.tools.find({"name": name}, {"version": 1}).sort("version", -1).limit(1)
        docs = await cursor.to_list(length=1)
        return (docs[0]["version"] + 1) if docs else 1


class AtlasToolStore:
    """Synchronous `ToolStore` over `AsyncAtlasToolStore`."""

    def __init__(self, uri: str, db_name: str) -> None:
        self._loop = _LoopThread()

        async def _create() -> AsyncAtlasToolStore:
            return AsyncAtlasToolStore(uri, db_name)

        self._async = self._loop.run(_create())
        try:
            self._loop.run(self._async.init())
        except Exception:
            self.close()
            raise

    @property
    def async_store(self) -> AsyncAtlasToolStore:
        return self._async

    def close(self) -> None:
        try:
            self._loop.run(self._async.close())
        finally:
            self._loop.stop()

    def drop(self) -> None:
        self._loop.run(self._async.drop())

    def save(self, record: ToolRecord) -> None:
        self._loop.run(self._async.save(record))

    def get(self, name: str, version: int | None = None) -> ToolRecord:
        return self._loop.run(self._async.get(name, version))

    def versions(self, name: str) -> list[ToolRecord]:
        return self._loop.run(self._async.versions(name))

    def list_tools(self, status: ToolStatus | None = None) -> list[ToolRecord]:
        return self._loop.run(self._async.list_tools(status))

    def set_status(self, name: str, version: int, status: ToolStatus) -> None:
        self._loop.run(self._async.set_status(name, version, status))

    def record_use(self, name: str, version: int, run_id: str, ok: bool) -> None:
        self._loop.run(self._async.record_use(name, version, run_id, ok))

    def next_version(self, name: str) -> int:
        return self._loop.run(self._async.next_version(name))


__all__ = [
    "AsyncAtlasRunStore",
    "AsyncAtlasToolStore",
    "AtlasRunStore",
    "AtlasToolStore",
]
