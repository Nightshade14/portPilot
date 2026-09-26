"""Renderer tests: render with Console(record=True, width=120) and assert on
export_text(). Views are pure over plain data, so they take fixture-loaded
dicts but never a store."""

from __future__ import annotations

from rich.console import Console

from portpilot import views
from portpilot.models import CaseResult, ContractResult, Decision, Policy


def _render(renderable) -> str:
    console = Console(record=True, width=120)
    console.print(renderable)
    return console.export_text()


def _outputs(fixture) -> list[ContractResult]:
    return [
        ContractResult.from_doc(a["content"])
        for a in fixture["artifacts"]
        if a["kind"] == "test_output"
    ]


def test_render_run_status_shows_id_status_and_attempts(load_demo):
    fx = load_demo("completed_run")
    milestones = [tuple(m) for m in fx["milestones"]]
    text = _render(views.render_run_status(fx["run"], milestones, _outputs(fx)))
    assert "run_a1b2c3d4e5f6" in text
    assert "completed" in text
    assert "attempt 1" in text and "policy v1" in text and "6/10" in text
    assert "attempt 2" in text and "policy v2" in text and "10/10" in text


def test_render_run_status_marks_current_milestone_for_paused_run(load_demo):
    fx = load_demo("paused_run")
    milestones = [tuple(m) for m in fx["milestones"]]
    text = _render(views.render_run_status(fx["run"], milestones, _outputs(fx)))
    assert "paused" in text
    assert "candidate_policy" in text
    # regeneration has not run yet, so it still appears in the progress line
    assert "regeneration" in text


def test_render_run_status_without_attempts_says_none_recorded():
    run = {"run_id": "run_empty000000", "status": "running", "current_milestone": "generation"}
    text = _render(views.render_run_status(run, [], []))
    assert "no attempts recorded yet" in text


def test_render_contract_result_table_lists_cases_and_total(load_demo):
    fx = load_demo("completed_run")
    v1 = next(r for r in _outputs(fx) if r.attempt == 1)
    text = _render(views.render_contract_result(v1))
    assert "normalize_happy_path" in text
    assert "PASS" in text and "FAIL" in text
    assert "passed" in text and "6/10" in text
    # the first diff line of a failing case is shown
    assert "status: source=422 target=400" in text


def test_render_policy_comparison_marks_fixed_and_decision(load_demo):
    fx = load_demo("completed_run")
    outputs = {r.attempt: r for r in _outputs(fx)}
    eval_content = next(a["content"] for a in fx["artifacts"] if a["kind"] == "evaluation")
    decision = Decision(**eval_content)
    policies = [Policy.from_doc(p) for p in fx["policies"]]
    text = _render(
        views.render_policy_comparison(
            policies,
            outputs[decision.baseline_attempt],
            outputs[decision.candidate_attempt],
            decision,
        )
    )
    assert "v1" in text and "v2" in text
    assert "retired" in text and "active" in text
    assert "fixed" in text
    assert "PROMOTED" in text
    assert "no regressions" in text


def test_render_policy_comparison_flags_a_regression():
    # baseline passes a,b; candidate passes only a -> b is a regression
    baseline = ContractResult(
        run_id="r",
        attempt=1,
        policy_version=1,
        passed=2,
        total=2,
        cases=[
            CaseResult("a", "success", True, {}, {}),
            CaseResult("b", "success", True, {}, {}),
        ],
    )
    candidate = ContractResult(
        run_id="r",
        attempt=2,
        policy_version=2,
        passed=1,
        total=2,
        cases=[
            CaseResult("a", "success", True, {}, {}),
            CaseResult("b", "success", False, {}, {}, ["broke"]),
        ],
    )
    decision = Decision(
        run_id="r",
        baseline_attempt=1,
        candidate_attempt=2,
        baseline_version=1,
        candidate_version=2,
        baseline_passed=2,
        candidate_passed=1,
        total=2,
        regressions=["b"],
        fixed=[],
        promoted=False,
        reason="regression on b",
    )
    text = _render(views.render_policy_comparison([], baseline, candidate, decision))
    assert "REGRESSION" in text
    assert "REJECTED" in text


def test_render_events_timeline_and_limit(load_demo):
    fx = load_demo("completed_run")
    text = _render(views.render_events(fx["events"]))
    assert "checkpoint" in text
    assert "run complete" in text
    # limit keeps only the most recent N
    limited = _render(views.render_events(fx["events"], limit=2))
    assert "run complete" in limited
    assert "analyzed Flask source" not in limited


def test_render_events_empty():
    text = _render(views.render_events([]))
    assert "no events" in text
