"""AtlasStore (pymongo). Owner: Lane B.

Collections: migration_runs, milestones, artifacts, policies, events.
Indexes: run_id on each run-scoped collection; unique (name, version) on
policies; (run_id, ts) on events.
"""

from __future__ import annotations

from typing import Any

from portpilot.models import ArtifactKind, Milestone, Policy, PolicyStatus


class AtlasStore:
    def __init__(self, uri: str, db_name: str = "portpilot") -> None:
        raise NotImplementedError("Lane B: AtlasStore")

    def create_run(self, source_path: str, policy_version: int) -> str:
        raise NotImplementedError

    def get_run(self, run_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def update_run(self, run_id: str, **fields: Any) -> None:
        raise NotImplementedError

    def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None:
        raise NotImplementedError

    def complete_milestone(
        self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]
    ) -> None:
        raise NotImplementedError

    def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]:
        raise NotImplementedError

    def put_artifact(
        self, run_id: str, kind: ArtifactKind, attempt: int, content: dict[str, Any]
    ) -> str:
        raise NotImplementedError

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def latest_artifact(self, run_id: str, kind: ArtifactKind) -> dict[str, Any] | None:
        raise NotImplementedError

    def artifacts(
        self, run_id: str, kind: ArtifactKind | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_policy(self, name: str, version: int | None = None) -> Policy:
        raise NotImplementedError

    def list_policies(self, name: str) -> list[Policy]:
        raise NotImplementedError

    def save_policy(self, policy: Policy) -> None:
        raise NotImplementedError

    def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None:
        raise NotImplementedError

    def log_event(self, run_id: str, type: str, milestone: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def events(self, run_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError
