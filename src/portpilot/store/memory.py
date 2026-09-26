"""InMemoryStore. Owner: Lane B. Due T+0:40 so other lanes can develop against it.

Must satisfy tests/test_store_contract.py exactly like AtlasStore.
"""

from __future__ import annotations

from typing import Any

from portpilot.models import ArtifactKind, Milestone, Policy, PolicyStatus


class InMemoryStore:
    def __init__(self) -> None:
        raise NotImplementedError("Lane B: InMemoryStore")

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
