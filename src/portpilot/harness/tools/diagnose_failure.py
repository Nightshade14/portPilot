"""diagnose_failure. Owner: Lane D.

`diagnose()` is pure and rule-based so it can be tested against the reference
targets without a store or an LLM. The @tool wrapper loads/persists.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from portpilot.models import ContractResult, Diagnosis

# Category ids used by create_candidate_policy rule blocks.
ERROR_STATUS_AND_SCHEMA = "error_status_and_schema"
DEFAULTS = "defaults"
COERCION = "coercion"


def diagnose(result: ContractResult) -> Diagnosis:
    """Map failed cases to categories, e.g. 422-vs-400 or $.error.* mismatch
    -> error_status_and_schema."""
    raise NotImplementedError("Lane D: diagnose")


@tool
def diagnose_failure(run_id: str, attempt: int) -> dict[str, Any]:
    """Convert this attempt's failed contract cases into a structured Diagnosis and
    store it as a diagnosis artifact.

    Args:
        run_id: The migration run id.
        attempt: The attempt whose test_output to diagnose.

    Returns:
        The Diagnosis as a dict, including its artifact id.
    """
    raise NotImplementedError("Lane D: diagnose_failure")
