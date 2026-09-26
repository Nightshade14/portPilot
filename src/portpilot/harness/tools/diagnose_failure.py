"""diagnose_failure. Owner: Lane D.

`diagnose()` is pure and rule-based so it can be tested against the reference
targets without a store or an LLM. The @tool wrapper loads/persists.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from portpilot.harness.context import ctx
from portpilot.models import CaseResult, ContractResult, Diagnosis

# Category ids used by create_candidate_policy rule blocks.
ERROR_STATUS_AND_SCHEMA = "error_status_and_schema"
DEFAULTS = "defaults"
COERCION = "coercion"
TARGET_UNREACHABLE = "target_unreachable"
BEHAVIOR_MISMATCH = "behavior_mismatch"


def _has_nested_error_shape(json: Any) -> bool:
    """True when the body carries the nested error.code / error.details shape."""
    if not isinstance(json, dict):
        return False
    error = json.get("error")
    return isinstance(error, dict) and "code" in error and "details" in error


def _classify(case: CaseResult) -> str:
    """Map one failed case to a category from its source/target dicts alone.

    The rules read the recorded source/target observations, not Lane A's exact
    human-readable diff wording, so this stays stable if diff phrasing changes.
    """
    source = case.source or {}
    target = case.target or {}

    # An unreachable target records {"error": <str>} instead of {status, json}.
    if "error" in target and "status" not in target:
        return TARGET_UNREACHABLE

    source_status = source.get("status")
    target_status = target.get("status")

    if isinstance(source_status, int) and source_status >= 400:
        status_differs = source_status != target_status
        missing_nested = not _has_nested_error_shape(target.get("json"))
        if status_differs or missing_nested:
            return ERROR_STATUS_AND_SCHEMA

    if case.category == "defaults":
        return DEFAULTS
    if case.category == "coercion":
        return COERCION

    return BEHAVIOR_MISMATCH


def _first_diff_or_status(case: CaseResult) -> str:
    """Cite the first diff line, else the source/target status pair."""
    if case.diff:
        return case.diff[0]
    src = (case.source or {}).get("status", "?")
    tgt = (case.target or {}).get("status", "?")
    return f"source status {src} vs target status {tgt}"


def diagnose(result: ContractResult) -> Diagnosis:
    """Map failed cases to categories, e.g. 422-vs-400 or $.error.* mismatch
    -> error_status_and_schema. Categories are deduped, first-seen order."""
    failed = [c for c in result.cases if not c.passed]

    categories: list[str] = []
    for case in failed:
        category = _classify(case)
        if category not in categories:
            categories.append(category)

    rationale_lines = [f"{case.case_id}: {_first_diff_or_status(case)}" for case in failed]
    rationale = "; ".join(rationale_lines) if rationale_lines else "no failed cases"

    return Diagnosis(
        run_id=result.run_id,
        attempt=result.attempt,
        categories=categories,
        failed_case_ids=[c.case_id for c in failed],
        rationale=rationale,
    )


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
    store = ctx().store
    outputs = store.artifacts(run_id, "test_output", attempt)
    if not outputs:
        raise ValueError(f"no test_output artifact for run {run_id} attempt {attempt}")
    result = ContractResult.from_doc(outputs[-1]["content"])

    diagnosis = diagnose(result)
    artifact_id = store.put_artifact(run_id, "diagnosis", attempt, diagnosis.to_doc())
    store.log_event(
        run_id,
        "decision",
        "diagnosis",
        {
            "attempt": attempt,
            "categories": diagnosis.categories,
            "failed_case_ids": diagnosis.failed_case_ids,
            "artifact_id": artifact_id,
        },
    )
    return {**diagnosis.to_doc(), "artifact_id": artifact_id}
