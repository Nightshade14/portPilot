"""evaluate_policy. Owner: Lane D.

Promotion rule (plan 4.5, never delegated to the LLM): promote only if
candidate.passed > baseline.passed AND no case that passed under the
baseline fails under the candidate.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from portpilot.models import ContractResult, Decision


def decide(run_id: str, baseline: ContractResult, candidate: ContractResult) -> Decision:
    raise NotImplementedError("Lane D: decide")


@tool
def evaluate_policy(run_id: str, baseline_attempt: int, candidate_attempt: int) -> dict[str, Any]:
    """Compare two attempts' contract results, apply the promotion rule, store an
    evaluation artifact and update both policies' status and decision.

    Args:
        run_id: The migration run id.
        baseline_attempt: Attempt generated under the active policy.
        candidate_attempt: Attempt generated under the candidate policy.

    Returns:
        The Decision as a dict.
    """
    raise NotImplementedError("Lane D: evaluate_policy")
