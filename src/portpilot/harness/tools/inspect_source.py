"""inspect_source. Owner: Lane C."""

from __future__ import annotations

from strands import tool


@tool
def inspect_source(run_id: str) -> str:
    """Read the Flask source fixture and store a structured source_analysis artifact
    (routes, fields, coercions, defaults, error handling). Never recomputed on resume.

    Args:
        run_id: The migration run id.

    Returns:
        The source_analysis artifact id.
    """
    raise NotImplementedError("Lane C: inspect_source")
