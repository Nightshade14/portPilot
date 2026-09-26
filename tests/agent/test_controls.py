"""Controls: pause and cancel via `run.control`."""

from __future__ import annotations

from conftest import make_deps, make_run
from fakes import ScriptedModel

from portpilot.agent.loop import run_migration


def _ltp_only_factory():
    from portpilot.agent.planner import LongTermPlanSpec, PhaseSpec

    class _Factory:
        def __call__(self, role: str) -> ScriptedModel:
            if role == "planner":
                return ScriptedModel(
                    structured_output_queue=[
                        LongTermPlanSpec(
                            phases=[
                                PhaseSpec(
                                    id="p1", title="t", goal="g", exit_criteria=[], modules=[]
                                )
                            ],
                            assumptions=[],
                            rationale="",
                        )
                    ]
                )
            return ScriptedModel()

    return _Factory()


def test_cancel_before_any_step_stops_the_run(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root, model_factory=_ltp_only_factory())
    run = make_run(control="cancel")
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "w1")

    assert result.status == "cancelled"
    assert result.control is None
    events = [e["type"] for e in deps.run_store.events(run.run_id)]
    assert events[-1] == "cancelled"
    # A cancel checked before any step ran still lets survey/LTP happen (loop.py runs
    # them unconditionally up front), but no step should have been planned/run.
    assert deps.run_store.steps(run.run_id) == []


def test_pause_before_any_step_stops_the_run(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root, model_factory=_ltp_only_factory())
    run = make_run(control="pause")
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "w1")

    assert result.status == "paused"
    events = [e["type"] for e in deps.run_store.events(run.run_id)]
    assert events[-1] == "paused"


def test_resume_after_pause_drives_the_run_to_completion(sandbox_root):
    """API contract (docs/api/CONTRACT.md): resume sets a paused run back to
    status=queued with control=None; that is the API layer's job, not loop.py's -- but
    loop.py must accept a queued run with no lease and drive it normally afterwards."""

    from portpilot.agent.planner import LongTermPlanSpec, NextStepsSpec, PhaseSpec

    class _Factory:
        def __call__(self, role: str) -> ScriptedModel:
            if role == "planner":
                return ScriptedModel(
                    structured_output_queue=[
                        LongTermPlanSpec(
                            phases=[
                                PhaseSpec(
                                    id="p1", title="t", goal="g", exit_criteria=[], modules=[]
                                )
                            ],
                            assumptions=[],
                            rationale="",
                        ),
                        NextStepsSpec(steps=[], goal_complete=True),
                    ]
                )
            return ScriptedModel()

    deps = make_deps(sandbox_root=sandbox_root, model_factory=_Factory())
    run = make_run(control="pause")
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "w1")
    assert result.status == "paused"

    # Simulate the API's resume endpoint (docs/api/CONTRACT.md: "Resume sets a paused
    # run back to status=queued with control=null").
    deps.run_store.update_run(run.run_id, status="queued", control=None)

    result2 = run_migration(deps, run.run_id, "w1")
    assert result2.status == "completed"
