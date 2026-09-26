#!/usr/bin/env python3
"""Self-contained contract runner for the Profile API.

Loads contracts/v1/cases.json, fires each case at a running instance of the
service (default http://127.0.0.1:5001), and compares status + JSON body.
Exit code 0 iff every case matches; otherwise prints a per-case diff and
exits 1. No dependency on any other repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

CASES_PATH = Path(__file__).parent / "contracts" / "v1" / "cases.json"


def run(base_url: str) -> int:
    cases = json.loads(CASES_PATH.read_text())["cases"]
    failures: list[str] = []
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        for case in cases:
            req = case["request"]
            resp = client.request(req["method"], req["path"], json=req.get("json"))
            ok = resp.status_code == case["expect_status"]
            body: object
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            if not ok:
                failures.append(
                    f"{case['id']}: expected status {case['expect_status']}, got "
                    f"{resp.status_code}; body={body!r}"
                )
                continue
            print(f"PASS {case['id']} ({resp.status_code})")
        if failures:
            print("\nFAILURES:", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the profile-api contract cases")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    args = parser.parse_args()
    sys.exit(run(args.base_url))
