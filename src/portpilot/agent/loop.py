"""The run state machine (lane-a.md build step 11, MVP_PLAN §3.7)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from portpilot.agent.executor import execute_step
from portpilot.agent.guard import LeaseLost
from portpilot.agent.planner import create_long_term_plan, next_steps, revise_plan
from portpilot.agent.reflect import reflect_on_step
from portpilot.agent.selector import select_tools
from portpilot.agent.survey import survey as run_survey
from portpilot.agent.verify import verify_step
from portpilot.core.interfaces import NotFound
from portpilot.core.models import Run, ShortTermPlan

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

MAX_STEP_ATTEMPTS = 2  # retries before revising the plan (lane-a.md build step 11 / §3.4)


def _ltp_excerpt(ltp, step: ShortTermPlan) -> str:
    for phase in ltp.phases:
        if phase.id == step.phase_id:
            return f"Phase {phase.id} -- {phase.title}: {phase.goal}\nExit criteria: {phase.exit_criteria}"
    return ""


def _relevant_knowledge(deps: AgentDeps, step: ShortTermPlan) -> list[dict]:
    hits = deps.knowledge.search(step.objective, kinds=["lesson", "gotcha"], limit=5)
    return [{"title": h.item.title, "body": h.item.body, "kind": h.item.kind} for h in hits]


def _latest_digest(deps: AgentDeps, run_id: str) -> str:
    from portpilot.agent.digest import _existing_digest_text

    return _existing_digest_text(deps, run_id)


def _record_failure_gotcha(deps: AgentDeps, run: Run, step: ShortTermPlan) -> None:
    from portpilot.core.models import KnowledgeItem, KnowledgeSource, new_id

    item = KnowledgeItem(
        id=new_id("gotcha"),
        kind="gotcha",
        title=f"Step failed: {step.title}",
        body=f"Acceptance checks failed on attempt {step.attempts} for objective: {step.objective}",
        sources=[KnowledgeSource(run_id=run.run_id, step_id=step.step_id, repo_url=run.repo_url)],
    )
    item_id = deps.knowledge.upsert(item)
    deps.run_store.log_event(
        run.run_id,
        "gotcha_recorded",
        step.step_id,
        {"item_id": item_id, "title": item.title, "merged": item_id != item.id},
    )


def _run_one_step(deps: AgentDeps, run: Run, ltp, step: ShortTermPlan) -> None:
    """Advance `step` through selecting_tools -> running -> verifying -> reflecting ->
    done|failed, resuming from whatever phase it is already in."""

    survey_data = {}
    for meta in deps.run_store.list_artifacts(run.run_id, kind="survey"):
        survey_data = deps.run_store.get_artifact(meta["artifact_id"])["content"]
        break

    if step.status == "planned":
        deps.run_store.update_step(step.step_id, status="selecting_tools")
        step.status = "selecting_tools"

    if step.status == "selecting_tools":
        step = select_tools(deps, run, step, survey_data)
        deps.run_store.update_step(step.step_id, status="running", started_at=deps.clock())
        step.status = "running"
        deps.run_store.log_event(
            run.run_id,
            "step_started",
            step.step_id,
            {"seq": step.seq, "title": step.title, "attempt": step.attempts + 1},
        )

    if step.status == "running":
        deps.run_store.update_run(run.run_id, current_step_id=step.step_id)
        step.attempts += 1
        deps.run_store.update_step(step.step_id, attempts=step.attempts)

        step = execute_step(
            deps,
            run,
            step,
            ltp_excerpt=_ltp_excerpt(ltp, step),
            digest=_latest_digest(deps, run.run_id),
            lessons_and_gotchas=_relevant_knowledge(deps, step),
        )
        deps.run_store.update_step(step.step_id, status="verifying")
        step.status = "verifying"

    if step.status == "verifying":
        ok = verify_step(deps, run, step)
        if ok:
            deps.run_store.update_step(step.step_id, status="reflecting", outcome="passed")
            step.status = "reflecting"
            step.outcome = "passed"
        else:
            deps.run_store.update_step(step.step_id, outcome="failed")
            step.outcome = "failed"
            deps.run_store.log_event(
                run.run_id,
                "step_failed",
                step.step_id,
                {"reason": "acceptance checks failed", "attempt": step.attempts},
            )
            _record_failure_gotcha(deps, run, step)

            if step.attempts < MAX_STEP_ATTEMPTS:
                deps.run_store.update_step(step.step_id, status="running")
                step.status = "running"
                _run_one_step(deps, run, ltp, step)
                return

            new_ltp = revise_plan(
                deps,
                run,
                ltp,
                reason=f"step {step.title!r} failed after {step.attempts} attempts",
                digest=_latest_digest(deps, run.run_id),
            )
            ltp.phases = new_ltp.phases  # keep the caller's `ltp` reference current
            ltp.version = new_ltp.version
            deps.run_store.update_step(step.step_id, status="failed")
            step.status = "failed"
            return

    if step.status == "reflecting":
        reflect_on_step(deps, run, step)
        from portpilot.agent.digest import update_digest

        update_digest(deps, run, step)
        commit_sha = deps.sandbox.commit(run.run_id, f"portpilot: step {step.seq} -- {step.title}")
        deps.run_store.update_step(
            step.step_id, status="done", commit_sha=commit_sha, ended_at=deps.clock()
        )
        step.status = "done"
        step.commit_sha = commit_sha
        deps.run_store.log_event(
            run.run_id,
            "checkpoint",
            step.step_id,
            {"step_id": step.step_id, "commit_sha": commit_sha},
        )


def _resumable_running_step(deps: AgentDeps, run: Run) -> ShortTermPlan | None:
    if not run.current_step_id:
        return None
    try:
        step = deps.run_store.get_step(run.current_step_id)
    except NotFound:
        return None
    return step if step.status not in ("done", "failed", "skipped") else None


def run_migration(deps: AgentDeps, run_id: str, worker_id: str) -> Run:
    """Drive one run to completion, failure, pause, or cancellation. Resumable: safe to
    call again after a crash or a different worker claiming the run (MVP_PLAN §3.7).
    `worker_id` identifies this call for lease heartbeats (StepPolicy re-checks
    `deps.settings.worker_id`, which must match the caller's lease owner)."""

    run = deps.run_store.get_run(run_id)
    was_resuming = bool(run.current_step_id)

    try:
        deps.sandbox.ensure(run.run_id, run.repo_url)

        survey_data = run_survey(deps, run)

        ltp = deps.run_store.latest_plan(run.run_id)
        if ltp is None:
            ltp = create_long_term_plan(deps, run, survey_data)
            deps.run_store.update_run(run.run_id, ltp_version=ltp.version)

        if was_resuming:
            deps.run_store.log_event(run.run_id, "resumed", None, {})

        resumable = _resumable_running_step(deps, run)
        if resumable is not None:
            _run_one_step(deps, run, ltp, resumable)

        run_deadline = time.monotonic() + run.budgets.max_minutes * 60
        while True:
            if time.monotonic() > run_deadline:
                reason = f"run exceeded its wall-clock budget ({run.budgets.max_minutes} min)"
                deps.run_store.update_run(run.run_id, status="failed", error=reason)
                deps.run_store.log_event(run.run_id, "failed", None, {"reason": reason})
                return deps.run_store.get_run(run.run_id)

            current = deps.run_store.get_run(run.run_id)
            if current.control == "cancel":
                deps.run_store.update_run(run.run_id, status="cancelled", control=None)
                deps.run_store.log_event(run.run_id, "cancelled", None, {})
                return deps.run_store.get_run(run.run_id)
            if current.control == "pause":
                deps.run_store.update_run(run.run_id, status="paused")
                deps.run_store.log_event(run.run_id, "paused", None, {})
                return deps.run_store.get_run(run.run_id)

            steps = deps.run_store.steps(run.run_id)
            if len(steps) >= run.budgets.max_steps:
                reason = f"run reached its max_steps budget ({run.budgets.max_steps})"
                deps.run_store.update_run(run.run_id, status="failed", error=reason)
                deps.run_store.log_event(run.run_id, "failed", None, {"reason": reason})
                return deps.run_store.get_run(run.run_id)

            pending = [s for s in steps if s.status not in ("done", "failed", "skipped")]
            if not pending:
                completed = [s for s in steps if s.status == "done"]
                failed = [s for s in steps if s.status == "failed"]
                gotchas = deps.knowledge.list_items(kinds=["gotcha"], run_id=run.run_id, limit=20)
                new_steps = next_steps(
                    deps,
                    run,
                    ltp,
                    _latest_digest(deps, run.run_id),
                    completed,
                    failed,
                    [{"title": g.title, "body": g.body} for g in gotchas],
                )
                if not new_steps:
                    deps.run_store.update_run(run.run_id, status="completed", current_step_id=None)
                    deps.run_store.log_event(run.run_id, "completed", None, {})
                    return deps.run_store.get_run(run.run_id)
                pending = new_steps

            for step in pending:
                _run_one_step(deps, run, ltp, step)

    except LeaseLost as exc:
        deps.run_store.update_run(run.run_id, status="failed", error=str(exc))
        deps.run_store.log_event(run.run_id, "failed", None, {"reason": str(exc)})
        return deps.run_store.get_run(run.run_id)


__all__ = ["MAX_STEP_ATTEMPTS", "run_migration"]
