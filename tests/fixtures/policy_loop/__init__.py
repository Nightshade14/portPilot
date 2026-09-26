"""Synthetic contract results and a tests-only FakeStore for the policy loop.

Everything here is derived from contracts/profile-api/v1/cases.json so the
synthetic results track the real suite. InMemoryStore is built by Lane B in
parallel and raises NotImplementedError on this branch, so the wrappers are
exercised against FakeStore, which implements only the methods the Lane D
tools call, matching store/base.py semantics.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from portpilot.config import CASES_PATH
from portpilot.models import CaseResult, ContractResult, Policy, PolicyStatus

# Field-order case ids (see cases.json / SPEC.md). Cases 5, 7, 8, 10 (1-indexed)
# are the error cases policy v1 is designed to miss.
_CASES = json.loads(CASES_PATH.read_text())["cases"]
CASE_IDS: list[str] = [c["id"] for c in _CASES]

V1_MISS_IDS = [CASE_IDS[i] for i in (4, 6, 7, 9)]  # error cases v1 misses
DEFAULTS_CASE_ID = "normalize_applies_defaults"

# Source-side observations for the four error cases: nested 422/404 bodies.
_NESTED_422 = {
    "status": 422,
    "json": {
        "error": {
            "code": "VALIDATION_FAILED",
            "message": "Invalid profile payload",
            "details": [{"field": "age", "issue": "not_coercible"}],
        }
    },
}
_NESTED_404 = {
    "status": 404,
    "json": {
        "error": {
            "code": "NOT_FOUND",
            "message": "Profile not found",
            "details": [{"field": "id", "issue": "not_found"}],
        }
    },
}
# Target-side observations under idiomatic Hono/zod v1: flat 400 (validation)
# and flat 404 (not found) without the nested error.code/error.details shape.
_FLAT_400 = {"status": 400, "json": {"error": "Bad Request"}}
_FLAT_404 = {"status": 404, "json": {"error": "Not Found"}}


def _source_for(case_id: str) -> dict[str, Any]:
    if case_id == "get_profile_not_found_returns_nested_404":
        return dict(_NESTED_404)
    return dict(_NESTED_422)


def _target_for(case_id: str) -> dict[str, Any]:
    if case_id == "get_profile_not_found_returns_nested_404":
        return dict(_FLAT_404)
    return dict(_FLAT_400)


def _pass_case(case_id: str, category: str) -> CaseResult:
    obs = {"status": 200, "json": {"ok": True}}
    return CaseResult(case_id, category, True, dict(obs), dict(obs), [])


def _error_fail_case(case_id: str) -> CaseResult:
    source = _source_for(case_id)
    target = _target_for(case_id)
    diff = [f"status {source['status']} != {target['status']}", "missing $.error.code"]
    return CaseResult(case_id, "error-schema", False, source, target, diff)


def _defaults_fail_case(case_id: str) -> CaseResult:
    source = {"status": 200, "json": {"country": "US", "newsletter": False, "tags": []}}
    target = {"status": 200, "json": {"country": None}}
    diff = ["$.country 'US' != None"]
    return CaseResult(case_id, "defaults", False, source, target, diff)


def _category_of(case_id: str) -> str:
    for c in _CASES:
        if c["id"] == case_id:
            return c["category"]
    return "success"


def v1_miss_result(run_id: str = "run_test", attempt: int = 1) -> ContractResult:
    """6/10: the four error cases fail (nested 422/404 source vs flat 400/404 target)."""
    cases: list[CaseResult] = []
    for case_id in CASE_IDS:
        if case_id in V1_MISS_IDS:
            cases.append(_error_fail_case(case_id))
        else:
            cases.append(_pass_case(case_id, _category_of(case_id)))
    passed = sum(1 for c in cases if c.passed)
    return ContractResult(run_id, attempt, 1, passed, len(cases), cases)


def good_result(run_id: str = "run_test", attempt: int = 2) -> ContractResult:
    """10/10 under the candidate policy."""
    cases = [_pass_case(cid, _category_of(cid)) for cid in CASE_IDS]
    return ContractResult(run_id, attempt, 2, len(cases), len(cases), cases)


def regressing_result(run_id: str = "run_test", attempt: int = 2) -> ContractResult:
    """Fixes the four error cases but breaks normalize_applies_defaults."""
    cases: list[CaseResult] = []
    for case_id in CASE_IDS:
        if case_id == DEFAULTS_CASE_ID:
            cases.append(_defaults_fail_case(case_id))
        else:
            cases.append(_pass_case(case_id, _category_of(case_id)))
    passed = sum(1 for c in cases if c.passed)
    return ContractResult(run_id, attempt, 2, passed, len(cases), cases)


class FakeStore:
    """Tests-only store implementing only the methods the Lane D tools call.

    Semantics mirror store/base.py: artifacts() returns matching docs ascending
    by insertion; get_policy(name) with no version returns the active one;
    save_policy rejects a duplicate (name, version); set_policy_status mutates
    status and records the decision. Everything else the Protocol declares is
    intentionally absent because Lane D never calls it.
    """

    def __init__(self) -> None:
        self._artifacts: list[dict[str, Any]] = []
        self._policies: dict[tuple[str, int], Policy] = {}
        self.events: list[dict[str, Any]] = []

    # --- artifacts ------------------------------------------------------
    def put_artifact(self, run_id: str, kind: str, attempt: int, content: dict[str, Any]) -> str:
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        self._artifacts.append(
            {
                "artifact_id": artifact_id,
                "run_id": run_id,
                "kind": kind,
                "attempt": attempt,
                "content": content,
            }
        )
        return artifact_id

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        for doc in self._artifacts:
            if doc["artifact_id"] == artifact_id:
                return doc
        raise KeyError(artifact_id)

    def artifacts(
        self, run_id: str, kind: str | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        return [
            doc
            for doc in self._artifacts
            if doc["run_id"] == run_id
            and (kind is None or doc["kind"] == kind)
            and (attempt is None or doc["attempt"] == attempt)
        ]

    # --- policies -------------------------------------------------------
    def save_policy(self, policy: Policy) -> None:
        key = (policy.name, policy.version)
        if key in self._policies:
            raise ValueError(f"policy {key} already exists")
        self._policies[key] = policy

    def get_policy(self, name: str, version: int | None = None) -> Policy:
        if version is not None:
            return self._policies[(name, version)]
        active = [p for p in self._policies.values() if p.name == name and p.status == "active"]
        if not active:
            raise KeyError(f"no active policy {name}")
        return active[0]

    def set_policy_status(
        self, name: str, version: int, status: PolicyStatus, decision: dict[str, Any]
    ) -> None:
        policy = self._policies[(name, version)]
        policy.status = status
        policy.decision = decision

    # --- events ---------------------------------------------------------
    def log_event(self, run_id: str, type: str, milestone: str, payload: dict[str, Any]) -> None:
        self.events.append(
            {"run_id": run_id, "type": type, "milestone": milestone, "payload": payload}
        )
