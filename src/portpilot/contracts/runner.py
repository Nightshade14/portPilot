"""Contract runner. Owner: Lane A.

Runs every case in cases.json against a source and a target base URL and
returns a ContractResult. A case passes only when every field listed in
`compare` matches exactly after `ignore_paths` are removed (plan 4.1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from portpilot.config import CASES_PATH, GOLDEN_PATH
from portpilot.models import CaseResult, ContractResult

REQUEST_TIMEOUT = 5.0


def load_cases(path: Path = CASES_PATH) -> dict[str, Any]:
    """Return the parsed suite: {"suite", "version", "cases": [...]}."""
    return json.loads(path.read_text())


def call_case(base_url: str, case: dict[str, Any]) -> dict[str, Any]:
    """Execute one case's request. Return {"status": int, "json": Any}
    or {"error": str} when the service is unreachable."""
    req = case["request"]
    method = req["method"].upper()
    url = f"{base_url}{req['path']}"
    try:
        resp = httpx.request(
            method,
            url,
            json=req.get("json"),
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        body = resp.text
    return {"status": resp.status_code, "json": body}


def _remove(node: Any, parts: list[str]) -> Any:
    if not isinstance(node, dict):
        return node
    head, *rest = parts
    if head not in node:
        return node
    result = dict(node)
    if rest:
        result[head] = _remove(result[head], rest)
    else:
        del result[head]
    return result


def _apply_ignores(obs: dict[str, Any], ignore_paths: list[str]) -> dict[str, Any]:
    """Return a copy of obs with each dotted ignore path removed from its body.

    A leading `json.` segment is optional; `error.message` and
    `json.error.message` both target obs["json"]["error"]["message"]. A path
    rooted at `status` is left untouched (a scalar cannot be partially stripped).
    """
    body = obs.get("json")
    for dotted in ignore_paths:
        parts = dotted.split(".")
        if parts and parts[0] == "json":
            parts = parts[1:]
        elif parts and parts[0] == "status":
            continue
        if parts and isinstance(body, dict):
            body = _remove(body, parts)
    result = dict(obs)
    if "json" in result:
        result["json"] = body
    return result


def compare_case(
    case: dict[str, Any], source: dict[str, Any], target: dict[str, Any]
) -> CaseResult:
    """Diff source vs target for one case into a CaseResult."""
    compare_fields = case.get("compare", ["status", "json"])
    ignore_paths = case.get("ignore_paths", [])

    diff: list[str] = []

    if "error" in target:
        diff.append(f"target unreachable: {target['error']}")
        return CaseResult(
            case_id=case["id"],
            category=case["category"],
            passed=False,
            source=source,
            target=target,
            diff=diff,
        )

    src = _apply_ignores(source, ignore_paths)
    tgt = _apply_ignores(target, ignore_paths)

    for field in compare_fields:
        s_val = src.get(field)
        t_val = tgt.get(field)
        if field == "status":
            if s_val != t_val:
                diff.append(f"status: source={s_val} target={t_val}")
        else:
            diff.extend(_diff_json("json", s_val, t_val))

    return CaseResult(
        case_id=case["id"],
        category=case["category"],
        passed=not diff,
        source=source,
        target=target,
        diff=diff,
    )


def _diff_json(prefix: str, source: Any, target: Any) -> list[str]:
    """Recursively diff two JSON values. Returns human-readable lines."""
    diffs: list[str] = []
    if isinstance(source, dict) and isinstance(target, dict):
        for key in source:
            path = f"{prefix}.{key}"
            if key not in target:
                diffs.append(f"{path}: missing in target")
            else:
                diffs.extend(_diff_json(path, source[key], target[key]))
        for key in target:
            if key not in source:
                diffs.append(f"{prefix}.{key}: unexpected in target")
    elif isinstance(source, list) and isinstance(target, list):
        if len(source) != len(target):
            diffs.append(f"{prefix}: length source={len(source)} target={len(target)}")
        else:
            for i, (s_item, t_item) in enumerate(zip(source, target)):
                diffs.extend(_diff_json(f"{prefix}[{i}]", s_item, t_item))
    elif source != target:
        diffs.append(f"{prefix}: source={source!r} target={target!r}")
    return diffs


def run_suite(
    source_url: str,
    target_url: str,
    *,
    run_id: str = "adhoc",
    attempt: int = 0,
    policy_version: int = 0,
    cases_path: Path = CASES_PATH,
) -> ContractResult:
    suite = load_cases(cases_path)
    results: list[CaseResult] = []
    for case in suite["cases"]:
        source_obs = call_case(source_url, case)
        target_obs = call_case(target_url, case)
        results.append(compare_case(case, source_obs, target_obs))
    passed = sum(1 for r in results if r.passed)
    return ContractResult(
        run_id=run_id,
        attempt=attempt,
        policy_version=policy_version,
        passed=passed,
        total=len(results),
        cases=results,
    )


def run_source_only(source_url: str, cases_path: Path = CASES_PATH) -> ContractResult:
    """Check the source against golden.json and each case's expect_status."""
    suite = load_cases(cases_path)
    golden = _load_golden()
    results: list[CaseResult] = []
    for case in suite["cases"]:
        obs = call_case(source_url, case)
        diff: list[str] = []
        if "error" in obs:
            diff.append(f"source unreachable: {obs['error']}")
        else:
            expect = case.get("expect_status")
            if expect is not None and obs.get("status") != expect:
                diff.append(f"status: expected={expect} actual={obs.get('status')}")
            if golden is not None and case["id"] in golden:
                expected_obs = golden[case["id"]]
                if obs.get("status") != expected_obs.get("status"):
                    diff.append(
                        f"status: golden={expected_obs.get('status')} actual={obs.get('status')}"
                    )
                diff.extend(_diff_json("json", expected_obs.get("json"), obs.get("json")))
        results.append(
            CaseResult(
                case_id=case["id"],
                category=case["category"],
                passed=not diff,
                # source-only: the "source" side is the golden expectation, "target"
                # is the live source we are checking.
                source=golden.get(case["id"], {}) if golden else {},
                target=obs,
                diff=diff,
            )
        )
    passed = sum(1 for r in results if r.passed)
    return ContractResult(
        run_id="source-only",
        attempt=0,
        policy_version=0,
        passed=passed,
        total=len(results),
        cases=results,
    )


def _load_golden(path: Path = GOLDEN_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def snapshot_golden(
    source_url: str, cases_path: Path = CASES_PATH, out_path: Path = GOLDEN_PATH
) -> dict[str, Any]:
    """Record the source's own responses to each case, write golden.json."""
    suite = load_cases(cases_path)
    golden: dict[str, Any] = {}
    for case in suite["cases"]:
        obs = call_case(source_url, case)
        golden[case["id"]] = obs
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(golden, indent=2, sort_keys=False) + "\n")
    return golden
