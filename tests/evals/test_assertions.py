"""Tests for evals/assertions.py: Sync 2, 3 and 4 checks against synthetic
metrics dicts (no live API or Docker needed)."""

from __future__ import annotations

from assertions import check_sync2, check_sync2_tool_picks, check_sync3, check_sync4


def _base_metrics(**overrides):
    metrics = {
        "run_id": "run_1",
        "status": "completed",
        "steps_total": 3,
        "steps_done": 3,
        "steps_failed": 0,
        "tokens_per_step": {"step_1": 100, "step_2": 200, "step_3": 300},
        "tool_schema_tokens_per_step": {"step_1": 500, "step_2": 500, "step_3": 500},
        "tools_created": [],
        "tools_reused": [],
        "cli_installed": [],
        "cli_refused": [],
        "compactions": [],
        "lessons_recorded": 1,
        "gotchas_recorded": 0,
    }
    metrics.update(overrides)
    return metrics


def test_check_sync2_passes_on_healthy_run():
    assert check_sync2(_base_metrics()) == []


def test_check_sync2_fails_with_fewer_than_3_steps():
    failures = check_sync2(_base_metrics(steps_total=2))
    assert any("at least 3 STPs" in f for f in failures)


def test_check_sync2_fails_with_no_lessons_or_gotchas():
    failures = check_sync2(_base_metrics(lessons_recorded=0, gotchas_recorded=0))
    assert any("lesson or gotcha" in f for f in failures)


def test_check_sync2_fails_with_zero_steps_done():
    failures = check_sync2(_base_metrics(steps_done=0))
    assert any("at least one step done" in f for f in failures)


def test_check_sync2_tool_picks_flags_over_budget_selection():
    picks_per_step = {
        "step_1": [{"name": f"tool_{i}", "reason": "needed"} for i in range(9)],
    }
    failures = check_sync2_tool_picks(picks_per_step)
    assert any("exceeds max 8" in f for f in failures)


def test_check_sync2_tool_picks_flags_missing_reason():
    picks_per_step = {"step_1": [{"name": "shell"}]}
    failures = check_sync2_tool_picks(picks_per_step)
    assert any("has no reason" in f for f in failures)


def test_check_sync2_tool_picks_passes_within_budget_with_reasons():
    picks_per_step = {
        "step_1": [{"name": "shell", "reason": "run tests"}],
        "step_2": [{"name": f"tool_{i}", "reason": "x"} for i in range(8)],
    }
    assert check_sync2_tool_picks(picks_per_step) == []


def test_check_sync3_passes_when_run2_reuses_run1_tool():
    run1 = _base_metrics(
        tools_created=[
            {"name": "http_contract_diff", "version": 1, "purpose": "diff http responses"}
        ]
    )
    run2 = _base_metrics(
        tools_reused=[{"name": "http_contract_diff", "version": 1, "reason": "reuse"}],
        tools_created=[],
    )
    assert check_sync3(run1, run2) == []


def test_check_sync3_fails_when_run1_created_nothing():
    run1 = _base_metrics(tools_created=[])
    run2 = _base_metrics()
    failures = check_sync3(run1, run2)
    assert any("expected at least one tool_created" in f for f in failures)


def test_check_sync3_fails_when_run2_does_not_reuse():
    run1 = _base_metrics(
        tools_created=[
            {"name": "http_contract_diff", "version": 1, "purpose": "diff http responses"}
        ]
    )
    run2 = _base_metrics(tools_reused=[])
    failures = check_sync3(run1, run2)
    assert any("expected a tool created in run 1" in f for f in failures)


def test_check_sync3_fails_when_run2_creates_duplicate_purpose_tool():
    run1 = _base_metrics(
        tools_created=[
            {"name": "http_contract_diff", "version": 1, "purpose": "diff http responses"}
        ]
    )
    run2 = _base_metrics(
        tools_reused=[{"name": "http_contract_diff", "version": 1, "reason": "reuse"}],
        tools_created=[
            {"name": "http_contract_diff_v2", "version": 1, "purpose": "diff http responses"}
        ],
    )
    failures = check_sync3(run1, run2)
    assert any("already covered by run 1" in f for f in failures)


def test_check_sync4_passes_on_clean_resume_with_compaction():
    metrics = _base_metrics(
        compactions=[
            {
                "tokens_before": 100000,
                "tokens_after": 20000,
                "messages_before": 50,
                "messages_after": 5,
            }
        ]
    )
    assert check_sync4(metrics) == []


def test_check_sync4_fails_without_a_terminal_status():
    metrics = _base_metrics(status="running")
    failures = check_sync4(metrics)
    assert any("terminal status" in f for f in failures)


def test_check_sync4_fails_with_re_run_failed_steps():
    metrics = _base_metrics(steps_failed=1, compactions=[{"tokens_before": 1, "tokens_after": 1}])
    failures = check_sync4(metrics)
    assert any("re-run-and-failed" in f for f in failures)


def test_check_sync4_fails_without_compaction_event():
    metrics = _base_metrics(compactions=[])
    failures = check_sync4(metrics)
    assert any("at least one compaction event" in f for f in failures)


def test_check_sync4_fails_when_compaction_missing_token_counts():
    metrics = _base_metrics(compactions=[{"messages_before": 5, "messages_after": 1}])
    failures = check_sync4(metrics)
    assert any("missing tokens_before/after" in f for f in failures)
