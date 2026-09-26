"""Frozen Store protocol (plan section 4.4). Owner: Lead.

Both InMemoryStore and AtlasStore implement this exactly; the shared test
suite in tests/test_store_contract.py runs against both.

Atlas collections: migration_runs, milestones, artifacts, policies, events.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from portpilot.models import ArtifactKind, Milestone, Policy, PolicyStatus

COLLECTIONS = ("migration_runs", "milestones", "artifacts", "policies", "events")


class StoreError(RuntimeError):
    pass


class NotFound(StoreError):
    pass


@runtime_checkable
class Store(Protocol):
    # --- runs -----------------------------------------------------------
    def create_run(self, source_path: str, policy_version: int) -> str:
        """Create a run with status="running"; return its run_id."""
        ...

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return the migration_runs doc. Raises NotFound."""
        ...

    def update_run(self, run_id: str, **fields: Any) -> None:
        """Set fields such as status, current_milestone, attempt. Bumps updated_at."""
        ...

    # --- milestones -----------------------------------------------------
    def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None: ...

    def complete_milestone(
        self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]
    ) -> None: ...

    def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]:
        """(name, attempt) pairs in completion order. Resume skips these."""
        ...

    # --- artifacts ------------------------------------------------------
    def put_artifact(
        self, run_id: str, kind: ArtifactKind, attempt: int, content: dict[str, Any]
    ) -> str:
        """Store an artifact; return artifact_id."""
        ...

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        """Return {"artifact_id", "run_id", "kind", "attempt", "content", "created_at"}."""
        ...

    def latest_artifact(self, run_id: str, kind: ArtifactKind) -> dict[str, Any] | None: ...

    def artifacts(
        self, run_id: str, kind: ArtifactKind | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        """All matching artifacts for the run, ascending by created_at."""
        ...

    # --- policies -------------------------------------------------------
    def get_policy(self, name: str, version: int | None = None) -> Policy:
        """version=None returns the single policy with status="active". Raises NotFound."""
        ...

    def list_policies(self, name: str) -> list[Policy]:
        """All versions, ascending."""
        ...

    def save_policy(self, policy: Policy) -> None:
        """Insert a new (name, version). Raises StoreError if it already exists."""
        ...

    def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None: ...

    # --- events ---------------------------------------------------------
    def log_event(self, run_id: str, type: str, milestone: str, payload: dict[str, Any]) -> None:
        """Append-only. type e.g. tool_call, tool_result, decision, failure, checkpoint."""
        ...

    def events(self, run_id: str) -> list[dict[str, Any]]:
        """Events for the run, ascending by ts."""
        ...
