"""create_candidate_policy. Owner: Lane D.

Deterministic and template-driven: parent body + rule blocks keyed by
diagnosis category, rationale citing failed case ids.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from portpilot.models import Diagnosis, Policy


def build_candidate(parent: Policy, diagnosis: Diagnosis) -> Policy:
    """Return Policy(version=parent.version+1, status="candidate", parent_version=...)."""
    raise NotImplementedError("Lane D: build_candidate")


@tool
def create_candidate_policy(run_id: str, diagnosis_id: str) -> dict[str, Any]:
    """Create and save a candidate migration policy from a stored diagnosis, and store
    a candidate_policy artifact.

    Args:
        run_id: The migration run id.
        diagnosis_id: Artifact id of the diagnosis to address.

    Returns:
        The candidate Policy as a dict.
    """
    raise NotImplementedError("Lane D: create_candidate_policy")
