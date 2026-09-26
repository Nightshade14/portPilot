"""persist_checkpoint. Owner: Lane B."""

from __future__ import annotations

from strands import tool


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
    raise NotImplementedError("Lane B: persist_checkpoint")
