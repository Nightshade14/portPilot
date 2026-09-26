"""AtlasStore (pymongo). Owner: Lane B.

Collections: migration_runs, milestones, artifacts, policies, events.
Indexes: run_id on each run-scoped collection; unique (name, version) on
policies; (run_id, ts) on events.

Direct find/insert/update, no ORM. Documents map 1:1 to the store contract;
the Mongo `_id` is never exposed to callers.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from portpilot.models import ArtifactKind, Milestone, Policy, PolicyStatus
from portpilot.store.base import NotFound, StoreError

_POLICY_FIELDS = tuple(Policy.__dataclass_fields__)


def _now() -> datetime:
    return datetime.now(UTC)


def _run_id() -> str:
    return f"run_{secrets.token_hex(6)}"


def _art_id() -> str:
    return f"art_{secrets.token_hex(6)}"


def _as_utc(value: Any) -> Any:
    """Mongo returns UTC datetimes; ensure they carry tzinfo even if the client
    handed back a naive value."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class AtlasStore:
    def __init__(self, uri: str, db_name: str = "portpilot") -> None:
        self._client: MongoClient = MongoClient(
            uri, serverSelectionTimeoutMS=8000, tz_aware=True, tzinfo=UTC
        )
        self._db = self._client[db_name]
        self.runs = self._db["migration_runs"]
        self.milestones = self._db["milestones"]
        self.arts = self._db["artifacts"]
        self.policies = self._db["policies"]
        self.evts = self._db["events"]

        self.runs.create_index([("run_id", ASCENDING)], unique=True)
        self.milestones.create_index([("run_id", ASCENDING)])
        self.arts.create_index([("run_id", ASCENDING)])
        self.arts.create_index([("artifact_id", ASCENDING)], unique=True)
        self.policies.create_index([("name", ASCENDING), ("version", ASCENDING)], unique=True)
        self.evts.create_index([("run_id", ASCENDING)])
        self.evts.create_index([("run_id", ASCENDING), ("ts", ASCENDING)])

    @staticmethod
    def _clean(doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if doc is None:
            return None
        doc.pop("_id", None)
        for key, value in doc.items():
            doc[key] = _as_utc(value)
        return doc

    # --- runs -----------------------------------------------------------
    def create_run(self, source_path: str, policy_version: int) -> str:
        run_id = _run_id()
        now = _now()
        self.runs.insert_one(
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

    def get_run(self, run_id: str) -> dict[str, Any]:
        doc = self.runs.find_one({"run_id": run_id})
        if doc is None:
            raise NotFound(f"run {run_id!r} not found")
        return self._clean(doc)  # type: ignore[return-value]

    def update_run(self, run_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        result = self.runs.update_one({"run_id": run_id}, {"$set": fields})
        if result.matched_count == 0:
            raise NotFound(f"run {run_id!r} not found")

    # --- milestones -----------------------------------------------------
    def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None:
        if self.runs.find_one({"run_id": run_id}, {"_id": 1}) is None:
            raise NotFound(f"run {run_id!r} not found")
        self.milestones.insert_one(
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
        self.runs.update_one(
            {"run_id": run_id},
            {"$set": {"current_milestone": name, "updated_at": _now()}},
        )

    def complete_milestone(
        self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]
    ) -> None:
        if self.runs.find_one({"run_id": run_id}, {"_id": 1}) is None:
            raise NotFound(f"run {run_id!r} not found")
        result = self.milestones.update_one(
            {
                "run_id": run_id,
                "name": name,
                "attempt": attempt,
                "status": "started",
            },
            {
                "$set": {
                    "status": "completed",
                    "completed_at": _now(),
                    "artifact_ids": list(artifact_ids),
                }
            },
        )
        if result.matched_count == 0:
            self.milestones.insert_one(
                {
                    "run_id": run_id,
                    "name": name,
                    "attempt": attempt,
                    "status": "completed",
                    "started_at": None,
                    "completed_at": _now(),
                    "artifact_ids": list(artifact_ids),
                }
            )

    def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]:
        cursor = self.milestones.find({"run_id": run_id, "status": "completed"}).sort(
            "completed_at", ASCENDING
        )
        return [(doc["name"], doc["attempt"]) for doc in cursor]

    # --- artifacts ------------------------------------------------------
    def put_artifact(
        self, run_id: str, kind: ArtifactKind, attempt: int, content: dict[str, Any]
    ) -> str:
        if self.runs.find_one({"run_id": run_id}, {"_id": 1}) is None:
            raise NotFound(f"run {run_id!r} not found")
        artifact_id = _art_id()
        self.arts.insert_one(
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

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        doc = self.arts.find_one({"artifact_id": artifact_id})
        if doc is None:
            raise NotFound(f"artifact {artifact_id!r} not found")
        return self._clean(doc)  # type: ignore[return-value]

    def latest_artifact(self, run_id: str, kind: ArtifactKind) -> dict[str, Any] | None:
        cursor = (
            self.arts.find({"run_id": run_id, "kind": kind})
            .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
            .limit(0)
        )
        docs = list(cursor)
        if not docs:
            return None
        return self._clean(docs[-1])

    def artifacts(
        self, run_id: str, kind: ArtifactKind | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"run_id": run_id}
        if kind is not None:
            query["kind"] = kind
        if attempt is not None:
            query["attempt"] = attempt
        cursor = self.arts.find(query).sort([("created_at", ASCENDING), ("_id", ASCENDING)])
        return [self._clean(doc) for doc in cursor]  # type: ignore[misc]

    # --- policies -------------------------------------------------------
    def _policy_from_doc(self, doc: dict[str, Any]) -> Policy:
        return Policy(**{k: doc[k] for k in _POLICY_FIELDS if k in doc})

    def get_policy(self, name: str, version: int | None = None) -> Policy:
        if version is None:
            doc = self.policies.find_one({"name": name, "status": "active"})
            if doc is None:
                raise NotFound(f"no active policy named {name!r}")
            return self._policy_from_doc(doc)
        doc = self.policies.find_one({"name": name, "version": version})
        if doc is None:
            raise NotFound(f"policy {name!r} v{version} not found")
        return self._policy_from_doc(doc)

    def list_policies(self, name: str) -> list[Policy]:
        cursor = self.policies.find({"name": name}).sort("version", ASCENDING)
        return [self._policy_from_doc(doc) for doc in cursor]

    def save_policy(self, policy: Policy) -> None:
        try:
            self.policies.insert_one(policy.to_doc())
        except DuplicateKeyError as exc:
            raise StoreError(f"policy {policy.name!r} v{policy.version} already exists") from exc

    def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None:
        result = self.policies.update_one(
            {"name": name, "version": version},
            {"$set": {"status": status, "decision": decision}},
        )
        if result.matched_count == 0:
            raise NotFound(f"policy {name!r} v{version} not found")

    # --- events ---------------------------------------------------------
    def log_event(self, run_id: str, type: str, milestone: str, payload: dict[str, Any]) -> None:
        seq = self.evts.count_documents({"run_id": run_id})
        self.evts.insert_one(
            {
                "run_id": run_id,
                "type": type,
                "milestone": milestone,
                "payload": payload,
                "ts": _now(),
                "seq": seq,
            }
        )

    def events(self, run_id: str) -> list[dict[str, Any]]:
        cursor = self.evts.find({"run_id": run_id}).sort([("ts", ASCENDING), ("seq", ASCENDING)])
        return [self._clean(doc) for doc in cursor]  # type: ignore[misc]
