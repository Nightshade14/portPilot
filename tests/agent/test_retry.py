"""Retry: a failing acceptance check retries, then revises the plan."""

from __future__ import annotations

from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn

from portpilot.agent.loop import MAX_STEP_ATTEMPTS, run_migration
from portpilot.agent.planner import LongTermPlanSpec, NextStepsSpec, PhaseSpec, ShortTermPlanSpec
from portpilot.agent.selector import ToolSelectionSpec


def test_failing_check_retries_then_revises_plan(sandbox_root):
    step_spec = ShortTermPlanSpec(
        phase_id="phase-1",
        title="Always fails",
        objective="do the thing",
        inputs=[],
        acceptance=[
            {"name": "always fails", "command": "false", "expect_exit": 0, "timeout_s": 10}
        ],
        capability_hints=[],
        max_turns=10,
        max_tokens=100_000,
        max_minutes=10,
    )

    class _Factory:
        def __init__(self) -> None:
            # complete_step called on every executor invocation; the harness's own
            # `false` check is what fails, MAX_STEP_ATTEMPTS times.
            self.executor = ScriptedModel(
                turns=[
                    ScriptedTurn(tool_calls=[ScriptedToolCall("complete_step", {"summary": "s"})])
                ]
            )
            self.planner = ScriptedModel(
                structured_output_queue=[
                    LongTermPlanSpec(
                        phases=[
                            PhaseSpec(
                                id="phase-1", title="P1", goal="g", exit_criteria=[], modules=[]
                            )
                        ],
                        assumptions=[],
                        rationale="",
                    ),
                    NextStepsSpec(steps=[step_spec]),
                    # revise_plan's structured call:
                    LongTermPlanSpec(
                        phases=[
                            PhaseSpec(
                                id="phase-1-revised",
                                title="P1 revised",
                                goal="g2",
                                exit_criteria=[],
                                modules=[],
                            )
                        ],
                        assumptions=["revised after repeated failure"],
                        rationale="the original approach did not work",
                    ),
                    NextStepsSpec(steps=[], goal_complete=True),
                ]
            )
            self.aux = ScriptedModel(
                structured_output_queue=[
                    ToolSelectionSpec(picks=[], missing_capabilities=[]),
                ]
            )

        def __call__(self, role: str) -> ScriptedModel:
            return {"executor": self.executor, "planner": self.planner, "aux": self.aux}[role]

    factory = _Factory()
    deps = make_deps(sandbox_root=sandbox_root, model_factory=factory)
    run = make_run()
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "w1")
    assert result.status == "completed"  # next_steps says goal_complete after the revision

    steps = deps.run_store.steps(run.run_id)
    assert len(steps) == 1
    failed_step = steps[0]
    assert failed_step.status == "failed"
    assert failed_step.attempts == MAX_STEP_ATTEMPTS

    events = deps.run_store.events(run.run_id)
    types = [e["type"] for e in events]
    assert types.count("step_failed") == MAX_STEP_ATTEMPTS
    assert "plan_revised" in types
    assert deps.run_store.get_run(run.run_id).ltp_version == 2

    revised_event = next(e for e in events if e["type"] == "plan_revised")
    assert set(revised_event["payload"].keys()) >= {"version", "phases", "reason"}
    assert revised_event["payload"]["version"] == 2

    # Both failures have the identical title/body, so the store's dedupe path (0.92
    # cosine threshold) merges them into one gotcha with seen_count=2, rather than two
    # separate entries -- that is the intended "same failure keeps compounding one
    # gotcha" behavior of a fuzzy-deduped knowledge store, not a miss.
    gotchas = deps.knowledge.list_items(kinds=["gotcha"], run_id=run.run_id)
    assert len(gotchas) == 1
    assert gotchas[0].seen_count == MAX_STEP_ATTEMPTS
