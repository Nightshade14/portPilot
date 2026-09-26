"""InMemoryStore. Owner: Lane B. Due T+0:40 so other lanes can develop against it.

Must satisfy tests/test_store_contract.py exactly like AtlasStore.
"""

from __future__ import annotations

import copy
import secrets
from datetime import UTC, datetime
from typing import Any

from portpilot.models import ArtifactKind, Milestone, Policy, PolicyStatus
from portpilot.store.base import NotFound, StoreError


def _now() -> datetime:
    return datetime.now(UTC)


def _run_id() -> str:
    return f"run_{secrets.token_hex(6)}"


def _art_id() -> str:
    return f"art_{secrets.token_hex(6)}"


class InMemoryStore:
    """Process-local store. Returns deep copies so callers cannot mutate state."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        # milestones in completion order per run
        self._milestones: list[dict[str, Any]] = []
        self._artifacts: dict[str, dict[str, Any]] = {}
        # insertion order of artifact ids, used to break created_at ties
        self._artifact_order: list[str] = []
        self._policies: list[Policy] = []
        self._events: list[dict[str, Any]] = []
        self._seq = 0
        # Monotonic tick to break created_at/completed_at ties deterministically.
        self._completion_tick = 0

    # --- runs -----------------------------------------------------------
    def create_run(self, source_path: str, policy_version: int) -> str:
        run_id = _run_id()
        now = _now()
        self._runs[run_id] = {
            "run_id": run_id,
            "source_path": source_path,
            "policy_version": policy_version,
            "status": "running",
            "current_milestone": None,
            "attempt": 0,
            "created_at": now,
            "updated_at": now,
        }
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._runs[run_id])
        except KeyError:
            raise NotFound(f"run {run_id!r} not found") from None

    def update_run(self, run_id: str, **fields: Any) -> None:
        if run_id not in self._runs:
            raise NotFound(f"run {run_id!r} not found")
        run = self._runs[run_id]
        run.update(copy.deepcopy(fields))
        run["updated_at"] = _now()

    # --- milestones -----------------------------------------------------
    def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None:
        if run_id not in self._runs:
            raise NotFound(f"run {run_id!r} not found")
        self._milestones.append(
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
        self._runs[run_id]["current_milestone"] = name
        self._runs[run_id]["updated_at"] = _now()

    def complete_milestone(
        self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]
    ) -> None:
        if run_id not in self._runs:
            raise NotFound(f"run {run_id!r} not found")
        for m in self._milestones:
            if m["run_id"] == run_id and m["name"] == name and m["attempt"] == attempt:
                m["status"] = "completed"
                m["completed_at"] = _now()
                m["artifact_ids"] = list(artifact_ids)
                self._completion_tick += 1
                m["_completed_seq"] = self._completion_tick
                return
        # No matching started milestone: create a completed one directly.
        self._completion_tick += 1
        self._milestones.append(
            {
                "run_id": run_id,
                "name": name,
                "attempt": attempt,
                "status": "completed",
                "started_at": None,
                "completed_at": _now(),
                "artifact_ids": list(artifact_ids),
                "_completed_seq": self._completion_tick,
            }
        )

    def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]:
        completed = [
            m for m in self._milestones if m["run_id"] == run_id and m["status"] == "completed"
        ]
        completed.sort(key=lambda m: (m["completed_at"], m["_completed_seq"]))
        return [(m["name"], m["attempt"]) for m in completed]

    # --- artifacts ------------------------------------------------------
    def put_artifact(
        self, run_id: str, kind: ArtifactKind, attempt: int, content: dict[str, Any]
    ) -> str:
        if run_id not in self._runs:
            raise NotFound(f"run {run_id!r} not found")
        artifact_id = _art_id()
        self._artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "kind": kind,
            "attempt": attempt,
            "content": copy.deepcopy(content),
            "created_at": _now(),
        }
        self._artifact_order.append(artifact_id)
        return artifact_id

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._artifacts[artifact_id])
        except KeyError:
            raise NotFound(f"artifact {artifact_id!r} not found") from None

    def latest_artifact(self, run_id: str, kind: ArtifactKind) -> dict[str, Any] | None:
        matches = self._matching_artifacts(run_id, kind, None)
        if not matches:
            return None
        # Newest by created_at; insertion order breaks ties (later insert wins).
        best = max(matches, key=lambda pair: (pair[1]["created_at"], pair[0]))
        return copy.deepcopy(best[1])

    def artifacts(
        self, run_id: str, kind: ArtifactKind | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        matches = self._matching_artifacts(run_id, kind, attempt)
        matches.sort(key=lambda pair: (pair[1]["created_at"], pair[0]))
        return [copy.deepcopy(a) for _, a in matches]

    def _matching_artifacts(
        self, run_id: str, kind: ArtifactKind | None, attempt: int | None
    ) -> list[tuple[int, dict[str, Any]]]:
        out: list[tuple[int, dict[str, Any]]] = []
        for order, artifact_id in enumerate(self._artifact_order):
            a = self._artifacts[artifact_id]
            if a["run_id"] != run_id:
                continue
            if kind is not None and a["kind"] != kind:
                continue
            if attempt is not None and a["attempt"] != attempt:
                continue
            out.append((order, a))
        return out

    # --- policies -------------------------------------------------------
    def get_policy(self, name: str, version: int | None = None) -> Policy:
        if version is None:
            for p in self._policies:
                if p.name == name and p.status == "active":
                    return copy.deepcopy(p)
            raise NotFound(f"no active policy named {name!r}")
        for p in self._policies:
            if p.name == name and p.version == version:
                return copy.deepcopy(p)
        raise NotFound(f"policy {name!r} v{version} not found")

    def list_policies(self, name: str) -> list[Policy]:
        matches = [copy.deepcopy(p) for p in self._policies if p.name == name]
        matches.sort(key=lambda p: p.version)
        return matches

    def save_policy(self, policy: Policy) -> None:
        for p in self._policies:
            if p.name == policy.name and p.version == policy.version:
                raise StoreError(f"policy {policy.name!r} v{policy.version} already exists")
        self._policies.append(copy.deepcopy(policy))

    def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None:
        for p in self._policies:
            if p.name == name and p.version == version:
                p.status = status
                p.decision = copy.deepcopy(decision)
                return
        raise NotFound(f"policy {name!r} v{version} not found")

    # --- events ---------------------------------------------------------
    def log_event(self, run_id: str, type: str, milestone: str, payload: dict[str, Any]) -> None:
        self._seq += 1
        self._events.append(
            {
                "run_id": run_id,
                "type": type,
                "milestone": milestone,
                "payload": copy.deepcopy(payload),
                "ts": _now(),
                "seq": self._seq,
            }
        )

    def events(self, run_id: str) -> list[dict[str, Any]]:
        matches = [copy.deepcopy(e) for e in self._events if e["run_id"] == run_id]
        matches.sort(key=lambda e: (e["ts"], e["seq"]))
        return matches
