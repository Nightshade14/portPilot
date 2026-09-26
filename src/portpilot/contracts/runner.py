"""Contract runner. Owner: Lane A.

Runs every case in cases.json against a source and a target base URL and
returns a ContractResult. A case passes only when every field listed in
`compare` matches exactly after `ignore_paths` are removed (plan 4.1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from portpilot.config import CASES_PATH
from portpilot.models import CaseResult, ContractResult


def load_cases(path: Path = CASES_PATH) -> dict[str, Any]:
    """Return the parsed suite: {"suite", "version", "cases": [...]}."""
    return json.loads(path.read_text())


def call_case(base_url: str, case: dict[str, Any]) -> dict[str, Any]:
    """Execute one case's request. Return {"status": int, "json": Any}
    or {"error": str} when the service is unreachable."""
    raise NotImplementedError("Lane A: call_case")


def compare_case(
    case: dict[str, Any], source: dict[str, Any], target: dict[str, Any]
) -> CaseResult:
    """Diff source vs target for one case into a CaseResult."""
    raise NotImplementedError("Lane A: compare_case")


def run_suite(
    source_url: str,
    target_url: str,
    *,
    run_id: str = "adhoc",
    attempt: int = 0,
    policy_version: int = 0,
    cases_path: Path = CASES_PATH,
) -> ContractResult:
    raise NotImplementedError("Lane A: run_suite")


def run_source_only(source_url: str, cases_path: Path = CASES_PATH) -> ContractResult:
    """Check the source against golden.json and each case's expect_status."""
    raise NotImplementedError("Lane A: run_source_only")
