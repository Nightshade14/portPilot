"""Unit tests for the contract runner's diff logic (no network)."""

from __future__ import annotations

from portpilot.contracts.runner import compare_case

CASE = {
    "id": "unit_case",
    "category": "success",
    "request": {"method": "POST", "path": "/x", "json": {}},
    "compare": ["status", "json"],
    "ignore_paths": [],
}


def _case(**over):
    return {**CASE, **over}


def test_compare_case_passes_on_identical_status_and_json():
    obs = {"status": 200, "json": {"a": 1, "b": [1, 2]}}
    result = compare_case(_case(), obs, {"status": 200, "json": {"a": 1, "b": [1, 2]}})
    assert result.passed
    assert result.diff == []


def test_compare_case_reports_status_diff_in_source_target_form():
    result = compare_case(
        _case(),
        {"status": 422, "json": {}},
        {"status": 400, "json": {}},
    )
    assert not result.passed
    assert "status: source=422 target=400" in result.diff


def test_compare_case_reports_missing_key_in_target():
    result = compare_case(
        _case(),
        {"status": 200, "json": {"error": {"code": "X"}}},
        {"status": 200, "json": {"error": {}}},
    )
    assert not result.passed
    assert "json.error.code: missing in target" in result.diff


def test_compare_case_reports_value_mismatch():
    result = compare_case(
        _case(),
        {"status": 200, "json": {"age": 42}},
        {"status": 200, "json": {"age": 41}},
    )
    assert not result.passed
    assert any("json.age" in line for line in result.diff)


def test_compare_case_reports_unexpected_key_in_target():
    result = compare_case(
        _case(),
        {"status": 200, "json": {"a": 1}},
        {"status": 200, "json": {"a": 1, "extra": 2}},
    )
    assert not result.passed
    assert "json.extra: unexpected in target" in result.diff


def test_compare_case_marks_unreachable_target_failed():
    result = compare_case(_case(), {"status": 200, "json": {}}, {"error": "ConnectError: boom"})
    assert not result.passed
    assert any("unreachable" in line for line in result.diff)


def test_ignore_paths_dotted_removes_field_before_diff():
    # error.message differs but is ignored; code differs and is not ignored.
    case = _case(ignore_paths=["error.message"])
    source = {"status": 422, "json": {"error": {"code": "V", "message": "src msg"}}}
    target = {"status": 422, "json": {"error": {"code": "V", "message": "tgt msg"}}}
    result = compare_case(case, source, target)
    assert result.passed
    assert result.diff == []


def test_ignore_paths_with_json_prefix_is_equivalent():
    case = _case(ignore_paths=["json.error.message"])
    source = {"status": 422, "json": {"error": {"code": "V", "message": "a"}}}
    target = {"status": 422, "json": {"error": {"code": "V", "message": "b"}}}
    result = compare_case(case, source, target)
    assert result.passed


def test_ignore_paths_does_not_hide_a_non_ignored_mismatch():
    case = _case(ignore_paths=["error.message"])
    source = {"status": 422, "json": {"error": {"code": "V", "message": "a"}}}
    target = {"status": 400, "json": {"error": {"code": "W", "message": "b"}}}
    result = compare_case(case, source, target)
    assert not result.passed
    assert "status: source=422 target=400" in result.diff
    assert "json.error.code: source='V' target='W'" in result.diff
