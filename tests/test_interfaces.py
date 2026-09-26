"""Guards on the frozen interfaces (plan section 4). If one fails, a lane
changed a shared contract without going through the Lead."""

from __future__ import annotations

import inspect

from portpilot.config import CASES_PATH
from portpilot.contracts.runner import load_cases
from portpilot.harness.agent import milestone_tools
from portpilot.harness.tools import ALL_TOOLS
from portpilot.models import (
    MILESTONES,
    CaseResult,
    ContractResult,
    Diagnosis,
    Policy,
)
from portpilot.store.atlas import AtlasStore
from portpilot.store.base import Store
from portpilot.store.memory import InMemoryStore

PLAN_CASE_IDS = [
    "normalize_happy_path",
    "normalize_coerces_numeric_strings",
    "normalize_applies_defaults",
    "normalize_trims_and_lowercases_email",
    "normalize_rejects_invalid_payload_with_422",
    "validate_accepts_valid_payload",
    "validate_missing_required_field_returns_422",
    "validate_uncoercible_age_returns_422",
    "get_profile_found",
    "get_profile_not_found_returns_nested_404",
]
EXPECTED_V1_FAILURES = {PLAN_CASE_IDS[i] for i in (4, 6, 7, 9)}


def test_cases_file_matches_plan_ids_in_order():
    suite = load_cases(CASES_PATH)
    assert suite["suite"] == "profile-api" and suite["version"] == 1
    assert [c["id"] for c in suite["cases"]] == PLAN_CASE_IDS


def test_every_case_is_well_formed():
    for case in load_cases()["cases"]:
        assert set(case) >= {"id", "category", "request", "compare", "ignore_paths"}
        assert case["request"]["method"] in {"GET", "POST"}
        assert case["request"]["path"].startswith("/profiles/")
        assert case["compare"] == ["status", "json"]


def test_error_cases_are_exactly_the_expected_v1_misses():
    errors = {c["id"] for c in load_cases()["cases"] if c["expect_status"] >= 400}
    assert errors == EXPECTED_V1_FAILURES


def test_contract_result_roundtrips_through_doc():
    r = ContractResult(
        run_id="r1",
        attempt=1,
        policy_version=1,
        passed=1,
        total=2,
        cases=[
            CaseResult(
                "a", "success", True, {"status": 200, "json": {}}, {"status": 200, "json": {}}
            ),
            CaseResult(
                "b",
                "error-schema",
                False,
                {"status": 422, "json": {}},
                {"status": 400, "json": {}},
                ["status 422 != 400"],
            ),
        ],
    )
    back = ContractResult.from_doc(r.to_doc())
    assert back == r
    assert back.passed_ids == {"a"} and back.failed_ids == {"b"}


def test_policy_and_diagnosis_roundtrip():
    p = Policy("flask-to-hono", 2, "candidate", "body", ["r"], 1, "why")
    assert Policy.from_doc(p.to_doc()) == p
    d = Diagnosis("r1", 1, ["error_status_and_schema"], ["b"], "422 vs 400")
    assert Diagnosis.from_doc(d.to_doc()) == d


def test_stores_implement_every_protocol_method():
    protocol_methods = {
        n for n, _ in inspect.getmembers(Store, inspect.isfunction) if not n.startswith("_")
    }
    for impl in (InMemoryStore, AtlasStore):
        missing = protocol_methods - set(dir(impl))
        assert not missing, f"{impl.__name__} missing {missing}"


def test_every_milestone_has_a_tool_list_ending_in_checkpoint():
    names = {t.tool_name for t in ALL_TOOLS}
    assert len(names) == 7
    for m in MILESTONES:
        tools = milestone_tools(m)
        assert tools[-1].tool_name == "persist_checkpoint"
