"""Offline end-to-end: survey, LTP, 3 STPs, tools selected with reasons, a lesson
recorded, a checkpoint commit per step, completed. Asserts event types/payload keys
against docs/api/CONTRACT.md."""

from __future__ import annotations

from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn

from portpilot.agent.digest import DigestSpec
from portpilot.agent.loop import run_migration
from portpilot.agent.planner import LongTermPlanSpec, NextStepsSpec, PhaseSpec, ShortTermPlanSpec
from portpilot.agent.reflect import LessonSpec, ReflectionSpec
from portpilot.agent.selector import ToolSelectionSpec


def _step_spec(phase_id: str, title: str, objective: str) -> ShortTermPlanSpec:
    return ShortTermPlanSpec(
        phase_id=phase_id,
        title=title,
        objective=objective,
        inputs=["src/"],
        acceptance=[{"name": "tests pass", "command": "true", "expect_exit": 0, "timeout_s": 60}],
        capability_hints=[],
        max_turns=10,
        max_tokens=100_000,
        max_minutes=10,
    )


class _RoleRoutedModelFactory:
    """Hands out a distinct `ScriptedModel` per role, each with its own structured
    output queue and executor tool-call script, so the offline suite fully controls
    every LLM call without touching the network."""

    def __init__(self) -> None:
        self.executor = ScriptedModel(
            turns=[
                ScriptedTurn(
                    tool_calls=[
                        ScriptedToolCall(
                            "record_lesson",
                            {
                                "title": "slugify needs unicode-aware lowering",
                                "body": "Using str.lower() alone mishandles some unicode; normalize first.",
                                "tags": ["python"],
                            },
                        )
                    ]
                ),
                ScriptedTurn(
                    tool_calls=[
                        ScriptedToolCall("complete_step", {"summary": "added slugify + tests"})
                    ]
                ),
            ]
        )
        self.planner = ScriptedModel(
            structured_output_queue=[
                LongTermPlanSpec(
                    phases=[
                        PhaseSpec(
                            id="phase-1",
                            title="Add slugify",
                            goal="Add slugify with tests",
                            exit_criteria=["tests pass"],
                            modules=["src/"],
                        )
                    ],
                    assumptions=["repo uses pytest"],
                    rationale="single small phase covers the goal",
                ),
                NextStepsSpec(
                    steps=[
                        _step_spec(
                            "phase-1", "Add slugify function", "Implement slugify(s) -> str"
                        ),
                        _step_spec(
                            "phase-1", "Add slugify tests", "Add pytest coverage for slugify"
                        ),
                        _step_spec(
                            "phase-1", "Wire into package", "Export slugify from the package"
                        ),
                    ]
                ),
                NextStepsSpec(steps=[], goal_complete=True),
            ]
        )
        self.aux = ScriptedModel(
            structured_output_queue=[
                ToolSelectionSpec(picks=[], missing_capabilities=[]),
                ReflectionSpec(
                    lessons=[LessonSpec(title="slugify lesson", body="unicode matters", tags=[])],
                    gotchas=[],
                    tool_feedback=[],
                ),
                DigestSpec(digest="Added slugify (step 1/3)."),
                ToolSelectionSpec(picks=[], missing_capabilities=[]),
                ReflectionSpec(lessons=[], gotchas=[], tool_feedback=[]),
                DigestSpec(digest="Added slugify + tests (step 2/3)."),
                ToolSelectionSpec(picks=[], missing_capabilities=[]),
                ReflectionSpec(lessons=[], gotchas=[], tool_feedback=[]),
                DigestSpec(digest="Added slugify, tests, export (step 3/3)."),
            ]
        )

    def __call__(self, role: str) -> ScriptedModel:
        return {"executor": self.executor, "planner": self.planner, "aux": self.aux}[role]


def test_offline_end_to_end(sandbox_root):
    factory = _RoleRoutedModelFactory()
    deps = make_deps(sandbox_root=sandbox_root, model_factory=factory)
    run = make_run()
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "test-worker")

    assert result.status == "completed"

    events = deps.run_store.events(run.run_id)
    types = [e["type"] for e in events]
    assert "survey_done" in types
    assert types.count("plan_created") == 1
    assert types.count("step_planned") == 3
    assert types.count("tools_selected") == 3
    assert types.count("step_verified") == 3
    assert types.count("checkpoint") == 3
    assert "lesson_recorded" in types
    assert types[-1] == "completed"

    survey_event = next(e for e in events if e["type"] == "survey_done")
    assert set(survey_event["payload"].keys()) >= {
        "languages",
        "files",
        "dockerfiles",
        "artifact_id",
    }

    plan_event = next(e for e in events if e["type"] == "plan_created")
    assert set(plan_event["payload"].keys()) >= {"version", "phases"}
    assert plan_event["payload"]["phases"][0].keys() >= {"id", "title"}

    for e in events:
        if e["type"] == "step_planned":
            assert set(e["payload"].keys()) >= {"step_id", "seq", "title", "phase_id"}
        if e["type"] == "tools_selected":
            assert set(e["payload"].keys()) >= {
                "candidates",
                "picks",
                "missing",
                "core_tools",
                "tool_schema_tokens",
            }
        if e["type"] == "step_verified":
            assert set(e["payload"].keys()) >= {"ok", "checks"}
            assert e["payload"]["ok"] is True
        if e["type"] == "checkpoint":
            assert set(e["payload"].keys()) >= {"step_id", "commit_sha"}
            assert e["payload"]["commit_sha"]
        if e["type"] == "lesson_recorded":
            assert set(e["payload"].keys()) >= {"item_id", "title", "merged"}

    steps = deps.run_store.steps(run.run_id)
    assert len(steps) == 3
    assert all(s.status == "done" for s in steps)
    assert all(s.commit_sha for s in steps)

    lessons = deps.knowledge.list_items(kinds=["lesson"])
    assert any(
        "slugify" in item.title.lower() or "slugify" in item.body.lower() for item in lessons
    )
