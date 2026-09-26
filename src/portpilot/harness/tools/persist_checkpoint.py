"""persist_checkpoint. Owner: Lane B."""

from __future__ import annotations

from datetime import UTC, datetime

from strands import tool

from portpilot.harness.context import ctx


@tool
def persist_checkpoint(run_id: str, milestone: str, note: str) -> str:
    """Record a resumable checkpoint event for the run at the given milestone.

    Args:
        run_id: The migration run id.
        milestone: Current milestone name.
        note: Short human-readable note.

    Returns:
        "ok".
    """
    store = ctx().store
    ts = datetime.now(UTC)
    store.log_event(run_id, "checkpoint", milestone, {"note": note})
    store.update_run(run_id, last_checkpoint={"milestone": milestone, "note": note, "ts": ts})
    return "ok"
