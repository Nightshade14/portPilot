"""Deterministic milestone state machine. Owner: Lane C.

Walks MILESTONES in order, skips anything in store.completed_milestones(),
checkpoints after each milestone, and on --pause-after sets status="paused"
and returns. `resume(run_id)` re-enters the same loop from stored state, so
source_analysis is never redone.

Each milestone may call only the tools in agent.milestone_tools(milestone),
and every inter-milestone value (artifact ids, policy versions) is read back
from the store rather than kept in memory -- that is what makes resume work
after a process restart.
"""

from __future__ import annotations

import time
import traceback
from typing import Any

from portpilot.config import POLICIES_DIR, POLICY_NAME
from portpilot.harness.agent import milestone_tools
from portpilot.harness.context import bind, ctx
from portpilot.harness.generation import Generator
from portpilot.models import MILESTONES, PAUSABLE_MILESTONES, Milestone
from portpilot.store.base import NotFound, Store

BASELINE_ATTEMPT = 1
CANDIDATE_ATTEMPT = 2

ATTEMPT_OF: dict[Milestone, int] = {
    "source_analysis": 0,
    "generation": BASELINE_ATTEMPT,
    "test": BASELINE_ATTEMPT,
    "diagnosis": BASELINE_ATTEMPT,
    "candidate_policy": BASELINE_ATTEMPT,
    "regeneration": CANDIDATE_ATTEMPT,
    "retest": CANDIDATE_ATTEMPT,
    "evaluation": CANDIDATE_ATTEMPT,
    "completion": CANDIDATE_ATTEMPT,
}
# Milestones that only make sense when the baseline failed some cases.
IMPROVEMENT_MILESTONES: frozenset[Milestone] = frozenset(
    {"diagnosis", "candidate_policy", "regeneration", "retest", "evaluation"}
)


class RunFailed(RuntimeError):
    pass


def _call(milestone: Milestone, tool_obj: Any, run_id: str, /, **kwargs: Any) -> Any:
    """Invoke one gated tool and record tool_call/tool_error events around it."""
    allowed = {t.tool_name for t in milestone_tools(milestone)}
    if tool_obj.tool_name not in allowed:
        raise RuntimeError(f"tool {tool_obj.tool_name} is not allowed at milestone {milestone}")
    store = ctx().store
    store.log_event(run_id, "tool_call", milestone, {"tool": tool_obj.tool_name, "args": kwargs})
    started = time.monotonic()
    try:
        result = tool_obj(**kwargs)
    except Exception as exc:
        store.log_event(
            run_id,
            "tool_error",
            milestone,
            {"tool": tool_obj.tool_name, "error": str(exc)[:2000]},
        )
        raise
    store.log_event(
        run_id,
        "tool_done",
        milestone,
        {"tool": tool_obj.tool_name, "seconds": round(time.monotonic() - started, 2)},
    )
    return result


def _latest(run_id: str, kind: str) -> dict[str, Any]:
    doc = ctx().store.latest_artifact(run_id, kind)  # type: ignore[arg-type]
    if doc is None:
        raise RunFailed(f"run {run_id} is missing its {kind} artifact")
    return doc


def _baseline_passed_everything(run_id: str) -> bool:
    doc = ctx().store.artifacts(run_id, "test_output", BASELINE_ATTEMPT)
    return bool(doc) and doc[-1]["content"]["passed"] == doc[-1]["content"]["total"]


def _step(run_id: str, milestone: Milestone) -> list[str]:
    """Run one milestone; return the artifact ids it produced."""
    from portpilot.harness import tools as t

    store = ctx().store
    run = store.get_run(run_id)
    if milestone == "source_analysis":
        return [_call(milestone, t.inspect_source, run_id, run_id=run_id)]
    if milestone == "generation":
        aid = _call(
            milestone,
            t.generate_target,
            run_id,
            run_id=run_id,
            attempt=BASELINE_ATTEMPT,
            policy_version=run["policy_version"],
        )
        return [aid]
    if milestone in ("test", "retest"):
        attempt = ATTEMPT_OF[milestone]
        result = _call(milestone, t.run_contract_tests, run_id, run_id=run_id, attempt=attempt)
        return [result["artifact_id"]]
    if milestone == "diagnosis":
        d = _call(milestone, t.diagnose_failure, run_id, run_id=run_id, attempt=BASELINE_ATTEMPT)
        return [d["artifact_id"]]
    if milestone == "candidate_policy":
        diagnosis_id = _latest(run_id, "diagnosis")["artifact_id"]
        p = _call(
            milestone, t.create_candidate_policy, run_id, run_id=run_id, diagnosis_id=diagnosis_id
        )
        store.update_run(run_id, candidate_version=p["version"])
        return [p["artifact_id"]]
    if milestone == "regeneration":
        candidate_version = run.get("candidate_version")
        if candidate_version is None:
            candidate_version = _latest(run_id, "candidate_policy")["content"]["version"]
        aid = _call(
            milestone,
            t.generate_target,
            run_id,
            run_id=run_id,
            attempt=CANDIDATE_ATTEMPT,
            policy_version=candidate_version,
        )
        return [aid]
    if milestone == "evaluation":
        d = _call(
            milestone,
            t.evaluate_policy,
            run_id,
            run_id=run_id,
            baseline_attempt=BASELINE_ATTEMPT,
            candidate_attempt=CANDIDATE_ATTEMPT,
        )
        store.update_run(run_id, promoted=d["promoted"], decision_reason=d["reason"])
        return [d["artifact_id"]]
    if milestone == "completion":
        summary = _summary(run_id)
        store.update_run(run_id, summary=summary)
        return []
    raise ValueError(f"unknown milestone {milestone!r}")


def _summary(run_id: str) -> dict[str, Any]:
    store = ctx().store
    attempts = []
    for doc in store.artifacts(run_id, "test_output"):
        c = doc["content"]
        attempts.append(
            {
                "attempt": c["attempt"],
                "policy_version": c["policy_version"],
                "passed": c["passed"],
                "total": c["total"],
            }
        )
    active = store.get_policy(POLICY_NAME)
    return {"attempts": attempts, "active_policy_version": active.version}


def _drive(run_id: str, pause_after: Milestone | None) -> str:
    from portpilot.harness import tools as t

    store = ctx().store
    done = {name for name, _ in store.completed_milestones(run_id)}
    if done:
        store.log_event(
            run_id, "resume", "", {"skipping_completed": [m for m in MILESTONES if m in done]}
        )
    store.update_run(run_id, status="running")
    for milestone in MILESTONES:
        if milestone in done:
            continue
        attempt = ATTEMPT_OF[milestone]
        skipped = milestone in IMPROVEMENT_MILESTONES and _baseline_passed_everything(run_id)
        store.start_milestone(run_id, milestone, attempt)
        store.update_run(run_id, current_milestone=milestone, attempt=attempt)
        try:
            artifact_ids = [] if skipped else _step(run_id, milestone)
        except Exception as exc:
            store.update_run(run_id, status="failed", error=f"{milestone}: {exc}"[:2000])
            store.log_event(
                run_id,
                "failure",
                milestone,
                {"error": str(exc)[:2000], "traceback": traceback.format_exc()[-4000:]},
            )
            raise RunFailed(f"run {run_id} failed at {milestone}: {exc}") from exc
        store.complete_milestone(run_id, milestone, attempt, artifact_ids)
        note = "skipped: baseline already passes every case" if skipped else "completed"
        _call(
            milestone, t.persist_checkpoint, run_id, run_id=run_id, milestone=milestone, note=note
        )
        if pause_after == milestone:
            store.update_run(run_id, status="paused")
            store.log_event(
                run_id, "paused", milestone, {"resume_with": f"portpilot resume {run_id}"}
            )
            return run_id
    store.update_run(run_id, status="completed", current_milestone="completion")
    return run_id


def _check_pause(pause_after: Milestone | None) -> None:
    if pause_after is not None and pause_after not in PAUSABLE_MILESTONES:
        raise ValueError(f"--pause-after must be one of {PAUSABLE_MILESTONES}, got {pause_after!r}")


def _ensure_seeded(store: Store) -> None:
    from portpilot.store.seed import seed_policy

    try:
        store.get_policy(POLICY_NAME)
    except NotFound:
        seed_policy(store, POLICIES_DIR / f"{POLICY_NAME}.v1.md", name=POLICY_NAME, version=1)


def start_run(
    store: Store,
    policy_version: int | None = None,
    pause_after: Milestone | None = None,
    generator: Generator | None = None,
) -> str:
    """Create a run and drive it. Returns run_id."""
    from portpilot.config import FIXTURE_DIR

    _check_pause(pause_after)
    bind(store, generator=generator)
    _ensure_seeded(store)
    version = policy_version or store.get_policy(POLICY_NAME).version
    store.get_policy(POLICY_NAME, version)  # NotFound early if it does not exist
    run_id = store.create_run(str(FIXTURE_DIR), version)
    store.log_event(run_id, "run_started", "", {"policy_version": version})
    return _drive(run_id, pause_after)


def resume(
    store: Store,
    run_id: str,
    pause_after: Milestone | None = None,
    generator: Generator | None = None,
) -> str:
    _check_pause(pause_after)
    bind(store, generator=generator)
    run = store.get_run(run_id)
    if run["status"] == "completed":
        return run_id
    return _drive(run_id, pause_after)
