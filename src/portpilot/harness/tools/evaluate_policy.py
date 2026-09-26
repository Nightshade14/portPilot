"""evaluate_policy. Owner: Lane D.

Promotion rule (plan 4.5, never delegated to the LLM): promote only if
candidate.passed > baseline.passed AND no case that passed under the
baseline fails under the candidate.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from portpilot.config import POLICY_NAME
from portpilot.harness.context import ctx
from portpilot.models import ContractResult, Decision


def decide(run_id: str, baseline: ContractResult, candidate: ContractResult) -> Decision:
    """Deterministic promotion rule. Promote iff the candidate strictly improves
    the pass count and regresses no case that the baseline passed."""
    baseline_ids = baseline.passed_ids
    candidate_ids = candidate.passed_ids

    fixed = sorted(candidate_ids - baseline_ids)
    regressions = sorted(baseline_ids - candidate_ids)

    improved = candidate.passed > baseline.passed
    no_regressions = not regressions
    promoted = improved and no_regressions

    if promoted:
        reason = (
            f"Promoted: candidate v{candidate.policy_version} passes "
            f"{candidate.passed}/{candidate.total} vs baseline "
            f"v{baseline.policy_version} {baseline.passed}/{baseline.total}; "
            f"fixed {fixed} with no regressions."
        )
    elif regressions:
        reason = (
            f"Rejected: candidate v{candidate.policy_version} regresses "
            f"{regressions} that baseline v{baseline.policy_version} passed."
        )
    else:
        reason = (
            f"Rejected: candidate v{candidate.policy_version} does not improve "
            f"on baseline v{baseline.policy_version} "
            f"({candidate.passed}/{candidate.total} vs "
            f"{baseline.passed}/{baseline.total})."
        )

    return Decision(
        run_id=run_id,
        baseline_attempt=baseline.attempt,
        candidate_attempt=candidate.attempt,
        baseline_version=baseline.policy_version,
        candidate_version=candidate.policy_version,
        baseline_passed=baseline.passed,
        candidate_passed=candidate.passed,
        total=candidate.total,
        regressions=regressions,
        fixed=fixed,
        promoted=promoted,
        reason=reason,
    )


def _one_result(store: Any, run_id: str, attempt: int) -> ContractResult:
    outputs = store.artifacts(run_id, "test_output", attempt)
    if not outputs:
        raise ValueError(f"no test_output artifact for run {run_id} attempt {attempt}")
    return ContractResult.from_doc(outputs[-1]["content"])


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
    store = ctx().store
    baseline = _one_result(store, run_id, baseline_attempt)
    candidate = _one_result(store, run_id, candidate_attempt)

    decision = decide(run_id, baseline, candidate)
    decision_doc = decision.to_doc()

    artifact_id = store.put_artifact(run_id, "evaluation", candidate_attempt, decision_doc)

    if decision.promoted:
        # Candidate wins: it becomes active; baseline is retired (kept for rollback).
        store.set_policy_status(POLICY_NAME, candidate.policy_version, "active", decision_doc)
        store.set_policy_status(POLICY_NAME, baseline.policy_version, "retired", decision_doc)
    else:
        # Candidate loses: it is rejected; the baseline stays active.
        store.set_policy_status(POLICY_NAME, candidate.policy_version, "rejected", decision_doc)

    store.log_event(
        run_id,
        "decision",
        "evaluation",
        {
            "promoted": decision.promoted,
            "baseline_version": decision.baseline_version,
            "candidate_version": decision.candidate_version,
            "fixed": decision.fixed,
            "regressions": decision.regressions,
            "artifact_id": artifact_id,
        },
    )
    return {**decision_doc, "artifact_id": artifact_id}
