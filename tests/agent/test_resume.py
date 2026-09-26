"""Resume: crash (raise inside a hook) at each step status, then resume with fresh
deps on the same stores. No completed step re-runs; survey and LTP are not redone."""

from __future__ import annotations

import pytest
from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn

from portpilot.agent.digest import DigestSpec
from portpilot.agent.loop import run_migration
from portpilot.agent.planner import LongTermPlanSpec, NextStepsSpec, PhaseSpec, ShortTermPlanSpec
from portpilot.agent.reflect import ReflectionSpec
from portpilot.agent.selector import ToolSelectionSpec


def _step_spec(phase_id: str, title: str, objective: str) -> ShortTermPlanSpec:
    return ShortTermPlanSpec(
        phase_id=phase_id,
        title=title,
        objective=objective,
        inputs=[],
        acceptance=[{"name": "ok", "command": "true", "expect_exit": 0, "timeout_s": 60}],
        capability_hints=[],
        max_turns=10,
        max_tokens=100_000,
        max_minutes=10,
    )


def _one_phase_ltp() -> LongTermPlanSpec:
    return LongTermPlanSpec(
        phases=[PhaseSpec(id="phase-1", title="Do it", goal="g", exit_criteria=[], modules=[])],
        assumptions=[],
        rationale="",
    )


def _make_factory(executor_turns):
    class _Factory:
        def __init__(self) -> None:
            self.executor = ScriptedModel(turns=executor_turns)
            self.planner = ScriptedModel(
                structured_output_queue=[
                    _one_phase_ltp(),
                    NextStepsSpec(steps=[_step_spec("phase-1", "Step A", "do the thing")]),
                    NextStepsSpec(steps=[], goal_complete=True),
                ]
            )
            self.aux = ScriptedModel(
                structured_output_queue=[
                    ToolSelectionSpec(picks=[], missing_capabilities=[]),
                    ReflectionSpec(lessons=[], gotchas=[], tool_feedback=[]),
                    DigestSpec(digest="done"),
                ]
            )

        def __call__(self, role: str) -> ScriptedModel:
            return {"executor": self.executor, "planner": self.planner, "aux": self.aux}[role]

    return _Factory()


def test_resume_after_survey_and_ltp_are_not_redone(sandbox_root):
    """A run that already has a survey artifact and a saved LTP does not redo either
    on a second `run_migration` call."""

    factory = _make_factory(
        [ScriptedTurn(tool_calls=[ScriptedToolCall("complete_step", {"summary": "s"})])]
    )
    deps = make_deps(sandbox_root=sandbox_root, model_factory=factory)
    run = make_run()
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "w1")
    assert result.status == "completed"

    events_before = deps.run_store.events(run.run_id)
    survey_count_before = sum(1 for e in events_before if e["type"] == "survey_done")
    plan_created_before = sum(1 for e in events_before if e["type"] == "plan_created")
    assert survey_count_before == 1
    assert plan_created_before == 1

    # Re-run against the same stores/sandbox: nothing pending, so it should just try to
    # plan more steps (planner queue is now exhausted) without redoing survey or LTP.
    deps.run_store.update_run(run.run_id, status="queued", current_step_id=None)
    with pytest.raises(Exception, match="exhausted|structured output tool"):
        run_migration(deps, run.run_id, "w1")

    events_after = deps.run_store.events(run.run_id)
    survey_count_after = sum(1 for e in events_after if e["type"] == "survey_done")
    plan_created_after = sum(1 for e in events_after if e["type"] == "plan_created")
    assert survey_count_after == 1, "survey should not be redone once its artifact exists"
    assert plan_created_after == 1, "LTP v1 should not be recreated once saved"


def test_resume_running_step_continues_without_rerunning_done_steps(sandbox_root, monkeypatch):
    """Crash right as a step transitions out of `running` (simulating a `kill -9` after
    the executor loop finished but before the step's status was durably updated), then
    resume with a fresh `run_migration` call on the same stores: the crashed step picks
    back up from `running` rather than restarting the run, and once done, nothing is
    ever redone."""

    factory = _make_factory(
        [
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall("record_lesson", {"title": "t", "body": "b", "tags": []})
                ]
            ),
            ScriptedTurn(tool_calls=[ScriptedToolCall("complete_step", {"summary": "s"})]),
        ]
    )
    deps = make_deps(sandbox_root=sandbox_root, model_factory=factory)
    run = make_run()
    deps.run_store.create_run(run)

    real_update_step = deps.run_store.update_step

    def crash_on_verifying_transition(step_id, **fields):
        if fields.get("status") == "verifying":
            raise RuntimeError("simulated crash")
        return real_update_step(step_id, **fields)

    monkeypatch.setattr(deps.run_store, "update_step", crash_on_verifying_transition)

    with pytest.raises(RuntimeError, match="simulated crash"):
        run_migration(deps, run.run_id, "w1")

    run_after_crash = deps.run_store.get_run(run.run_id)
    assert run_after_crash.current_step_id is not None
    crashed_step = deps.run_store.get_step(run_after_crash.current_step_id)
    assert crashed_step.status == "running"

    monkeypatch.setattr(deps.run_store, "update_step", real_update_step)

    result = run_migration(deps, run.run_id, "w1")
    assert result.status == "completed"

    steps = deps.run_store.steps(run.run_id)
    assert len(steps) == 1
    assert steps[0].status == "done"

    events = deps.run_store.events(run.run_id)
    assert sum(1 for e in events if e["type"] == "resumed") == 1
    assert sum(1 for e in events if e["type"] == "survey_done") == 1
    assert sum(1 for e in events if e["type"] == "plan_created") == 1
    assert sum(1 for e in events if e["type"] == "checkpoint") == 1
