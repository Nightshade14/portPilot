"""run_contract_tests. Owner: Lane C (thin wrapper over Lane A's runner)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strands import tool

from portpilot.contracts.runner import run_suite
from portpilot.contracts.services import flask_source, hono_target
from portpilot.harness.context import ctx


@tool
def run_contract_tests(run_id: str, attempt: int) -> dict[str, Any]:
    """Boot the Flask source and this attempt's generated target, run the contract
    suite, and store the ContractResult as a test_output artifact.

    Args:
        run_id: The migration run id.
        attempt: Which generated target to test.

    Returns:
        The ContractResult as a dict (passed, total, per-case results).
    """
    store = ctx().store
    targets = store.artifacts(run_id, "target_version", attempt)
    if not targets:
        raise RuntimeError(f"run {run_id} has no target_version for attempt {attempt}")
    target = targets[-1]["content"]

    with flask_source() as source_url, hono_target(Path(target["path"])) as target_url:
        result = run_suite(
            source_url,
            target_url,
            run_id=run_id,
            attempt=attempt,
            policy_version=target["policy_version"],
        )
    doc = result.to_doc()
    artifact_id = store.put_artifact(run_id, "test_output", attempt, doc)
    store.log_event(
        run_id,
        "tool_result",
        "test" if attempt == 1 else "retest",
        {
            "tool": "run_contract_tests",
            "artifact_id": artifact_id,
            "policy_version": result.policy_version,
            "passed": result.passed,
            "total": result.total,
            "failed": sorted(result.failed_ids),
        },
    )
    return {**doc, "artifact_id": artifact_id}
