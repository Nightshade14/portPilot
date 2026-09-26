"""Lane D policy loop: diagnose, build_candidate, decide, and the @tool wrappers.

Pure functions are tested directly; the wrappers run against a tests-only
FakeStore (Lane B's InMemoryStore is built in parallel and is a stub here).
"""

from __future__ import annotations

from pathlib import Path

from fixtures.policy_loop import (
    DEFAULTS_CASE_ID,
    V1_MISS_IDS,
    FakeStore,
    good_result,
    regressing_result,
    v1_miss_result,
)

from portpilot.config import POLICY_NAME
from portpilot.harness.context import bind
from portpilot.harness.tools.create_candidate_policy import (
    build_candidate,
    create_candidate_policy,
)
from portpilot.harness.tools.diagnose_failure import diagnose, diagnose_failure
from portpilot.harness.tools.evaluate_policy import decide, evaluate_policy
from portpilot.models import Policy

POLICIES_DIR = Path(__file__).resolve().parents[1] / "policies"
V1_TEXT = (POLICIES_DIR / "flask-to-hono.v1.md").read_text()
V2_EXPECTED_TEXT = (POLICIES_DIR / "flask-to-hono.v2.expected.md").read_text()

_VERBATIM_SCHEMA = (
    '{"error": {"code": "VALIDATION_FAILED", "message": "Invalid profile payload",\n'
    '           "details": [{"field": "age", "issue": "not_coercible"}]}}'
)


def _seed_active_v1(store: FakeStore) -> Policy:
    v1 = Policy(
        name=POLICY_NAME,
        version=1,
        status="active",
        body="# flask-to-hono v1\n\n## Rules\n- idiomatic hono",
        rules=["idiomatic hono"],
    )
    store.save_policy(v1)
    return v1


# --- policy text oracle -------------------------------------------------


def test_v1_policy_omits_legacy_status_and_error_schema():
    assert "422" not in V1_TEXT
    assert "VALIDATION_FAILED" not in V1_TEXT


def test_v2_expected_contains_verbatim_schema_and_422():
    assert "422" in V2_EXPECTED_TEXT
    assert _VERBATIM_SCHEMA in V2_EXPECTED_TEXT


# --- diagnose -----------------------------------------------------------


def test_diagnose_v1_miss_returns_error_status_and_schema_with_four_ids():
    diagnosis = diagnose(v1_miss_result())
    assert diagnosis.categories == ["error_status_and_schema"]
    assert set(diagnosis.failed_case_ids) == set(V1_MISS_IDS)
    for case_id in V1_MISS_IDS:
        assert case_id in diagnosis.rationale


def test_diagnose_good_result_has_no_categories():
    diagnosis = diagnose(good_result())
    assert diagnosis.categories == []
    assert diagnosis.failed_case_ids == []


def test_diagnose_regression_classifies_defaults():
    diagnosis = diagnose(regressing_result())
    assert diagnosis.categories == ["defaults"]
    assert diagnosis.failed_case_ids == [DEFAULTS_CASE_ID]


# --- build_candidate ----------------------------------------------------


def test_build_candidate_sets_version_status_and_parent():
    parent = Policy(POLICY_NAME, 1, "active", "# body\n\n## Rules\n- a", ["a"])
    diagnosis = diagnose(v1_miss_result())
    candidate = build_candidate(parent, diagnosis)
    assert candidate.version == 2
    assert candidate.status == "candidate"
    assert candidate.parent_version == 1
    assert candidate.rules[0] == "a" and len(candidate.rules) == 2


def test_candidate_error_block_carries_verbatim_schema_and_422():
    parent = Policy(POLICY_NAME, 1, "active", "# body\n\n## Rules\n- a", ["a"])
    candidate = build_candidate(parent, diagnose(v1_miss_result()))
    assert "## Rule block: error_status_and_schema" in candidate.body
    assert _VERBATIM_SCHEMA in candidate.body
    assert "422" in candidate.body and "404" in candidate.body
    normalized = " ".join(candidate.body.split())
    assert "do not rely on default error responses" in normalized
    # rationale cites the failed case ids
    for case_id in V1_MISS_IDS:
        assert case_id in candidate.rationale


# --- decide -------------------------------------------------------------


def test_decide_miss_to_good_promotes():
    decision = decide("run_test", v1_miss_result(), good_result())
    assert decision.promoted is True
    assert set(decision.fixed) == set(V1_MISS_IDS)
    assert decision.regressions == []
    assert decision.baseline_version == 1 and decision.candidate_version == 2


def test_decide_good_to_miss_rejects():
    decision = decide("run_test", good_result(attempt=1), v1_miss_result(attempt=2))
    assert decision.promoted is False
    assert set(decision.regressions) == set(V1_MISS_IDS)


def test_decide_regression_vetoes_promotion():
    decision = decide("run_test", v1_miss_result(), regressing_result())
    assert decision.promoted is False
    assert DEFAULTS_CASE_ID in decision.regressions


# --- wrappers end to end ------------------------------------------------


def test_diagnose_failure_wrapper_persists_diagnosis():
    store = FakeStore()
    bind(store)
    result = v1_miss_result(run_id="run_e2e", attempt=1)
    store.put_artifact("run_e2e", "test_output", 1, result.to_doc())

    out = diagnose_failure("run_e2e", 1)
    assert out["categories"] == ["error_status_and_schema"]
    assert store.get_artifact(out["artifact_id"])["kind"] == "diagnosis"
    assert any(e["milestone"] == "diagnosis" for e in store.events)


def test_create_candidate_policy_wrapper_saves_and_persists():
    store = FakeStore()
    bind(store)
    _seed_active_v1(store)
    result = v1_miss_result(run_id="run_e2e", attempt=1)
    store.put_artifact("run_e2e", "test_output", 1, result.to_doc())
    diag = diagnose_failure("run_e2e", 1)

    out = create_candidate_policy("run_e2e", diag["artifact_id"])
    assert out["version"] == 2 and out["status"] == "candidate"
    saved = store.get_policy(POLICY_NAME, 2)
    assert saved.status == "candidate"
    assert _VERBATIM_SCHEMA in saved.body
    assert store.get_artifact(out["artifact_id"])["kind"] == "candidate_policy"


def test_evaluate_policy_wrapper_promotes_and_retires_baseline():
    store = FakeStore()
    bind(store)
    _seed_active_v1(store)
    store.save_policy(Policy(POLICY_NAME, 2, "candidate", "# v2", ["r"], parent_version=1))
    store.put_artifact("run_e2e", "test_output", 1, v1_miss_result(attempt=1).to_doc())
    store.put_artifact("run_e2e", "test_output", 2, good_result(attempt=2).to_doc())

    out = evaluate_policy("run_e2e", 1, 2)
    assert out["promoted"] is True
    assert store.get_policy(POLICY_NAME, 2).status == "active"
    assert store.get_policy(POLICY_NAME, 1).status == "retired"
    assert store.get_policy(POLICY_NAME, 1).decision is not None
    assert store.get_artifact(out["artifact_id"])["kind"] == "evaluation"


def test_evaluate_policy_wrapper_rejects_regression_and_keeps_baseline_active():
    store = FakeStore()
    bind(store)
    _seed_active_v1(store)
    store.save_policy(Policy(POLICY_NAME, 2, "candidate", "# v2", ["r"], parent_version=1))
    store.put_artifact("run_e2e", "test_output", 1, v1_miss_result(attempt=1).to_doc())
    store.put_artifact("run_e2e", "test_output", 2, regressing_result(attempt=2).to_doc())

    out = evaluate_policy("run_e2e", 1, 2)
    assert out["promoted"] is False
    assert store.get_policy(POLICY_NAME, 2).status == "rejected"
    assert store.get_policy(POLICY_NAME, 1).status == "active"
