"""Deterministic milestone state machine. Owner: Lane C.

Walks MILESTONES in order, skips anything in store.completed_milestones(),
checkpoints after each milestone, and on --pause-after sets status="paused"
and returns. `resume(run_id)` re-enters the same loop from Atlas state
without redoing source_analysis.
"""

from __future__ import annotations

from portpilot.models import Milestone
from portpilot.store.base import Store


def start_run(
    store: Store, policy_version: int | None = None, pause_after: Milestone | None = None
) -> str:
    """Create a run and drive it. Returns run_id."""
    raise NotImplementedError("Lane C: start_run")


def resume(store: Store, run_id: str, pause_after: Milestone | None = None) -> str:
    raise NotImplementedError("Lane C: resume")
