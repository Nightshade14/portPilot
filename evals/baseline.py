#!/usr/bin/env python3
"""Baseline image measurements for the E2 and E3 fixture repos (MVP_PLAN §8, Lane E).

For each repo, measures:
  - image size, from a host `docker build` then `docker save` to a tarball;
  - trivy CVE counts by severity, via `docker run --rm` of the pinned
    `aquasec/trivy` image against the docker-archive tarball;
  - dive efficiency and wasted bytes, via the pinned `wagoodman/dive` image
    in CI mode against the same tarball;
  - hadolint findings, via the pinned `hadolint/hadolint` image against the
    repo's Dockerfile.

Writes results to evals/baselines.json. Containers/images built here are
named/tagged with the `pp-test-e-` prefix and removed at the end (built
images are removed too; only the tarballs and baselines.json persist).

Pinned scanner images (tag + digest -- see docs/spikes/S3_SANDBOX.md for how
these versions were chosen; digests confirmed with `docker inspect --format
'{{index .RepoDigests 0}}'` after a fresh pull on 2026-09-26, arm64):
  aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
  wagoodman/dive:v0.13.1@sha256:f1886e6c32c094fc41a623c1989f5cb3e48aa766da5f0be233f911fc1d85ce10
  hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d

Usage:
  uv run python evals/baseline.py                 # both E2 and E3
  uv run python evals/baseline.py --repo e2        # just one
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = Path(__file__).resolve().parent
REPOS = {
    "e2": EVALS_DIR / "repos" / "e2-bloated-python-service",
    "e3": EVALS_DIR / "repos" / "e3-bloated-node-service",
}

TRIVY_IMAGE = (
    "aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969"
)
DIVE_IMAGE = (
    "wagoodman/dive:v0.13.1@sha256:f1886e6c32c094fc41a623c1989f5cb3e48aa766da5f0be233f911fc1d85ce10"
)
HADOLINT_IMAGE = "hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d"

CONTAINER_PREFIX = "pp-test-e-"


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=False, capture_output=True, text=True, **kwargs)


def _check(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    result = _run(cmd, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def build_image(repo: str, repo_dir: Path, tmp_dir: Path) -> tuple[str, Path, int, float]:
    """Build the repo's Dockerfile, save it as a docker-archive tarball.

    Returns (image_tag, tarball_path, size_bytes, build_seconds).
    """
    tag = f"{CONTAINER_PREFIX}{repo}:baseline"
    start = time.monotonic()
    _check(["docker", "build", "-t", tag, str(repo_dir)])
    build_seconds = time.monotonic() - start

    tarball = tmp_dir / f"{repo}.tar"
    _check(["docker", "save", "-o", str(tarball), tag])
    size_bytes = tarball.stat().st_size
    return tag, tarball, size_bytes, build_seconds


def run_trivy(tarball: Path) -> dict[str, Any]:
    cache_dir = tarball.parent / "trivy-cache"
    cache_dir.mkdir(exist_ok=True)
    container = f"{CONTAINER_PREFIX}trivy-{tarball.stem}"
    result = _check(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            container,
            "-v",
            f"{tarball.parent}:/scan",
            "-v",
            f"{cache_dir}:/root/.cache",
            TRIVY_IMAGE,
            "image",
            "--input",
            f"/scan/{tarball.name}",
            "--format",
            "json",
            "--quiet",
        ]
    )
    report = json.loads(result.stdout)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for res in report.get("Results") or []:
        for vuln in res.get("Vulnerabilities") or []:
            sev = vuln.get("Severity", "UNKNOWN")
            counts[sev] = counts.get(sev, 0) + 1
    return counts


def run_dive(tarball: Path) -> dict[str, Any]:
    out_path = tarball.parent / f"{tarball.stem}.dive.json"
    container = f"{CONTAINER_PREFIX}dive-{tarball.stem}"
    _check(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            container,
            "-v",
            f"{tarball.parent}:/scan",
            "-e",
            "CI=true",
            "-e",
            "HOME=/scan",
            DIVE_IMAGE,
            "--source",
            "docker-archive",
            f"/scan/{tarball.name}",
            "--ci",
            "--json",
            f"/scan/{out_path.name}",
        ]
    )
    report = json.loads(out_path.read_text())
    summary = report.get("image", {})
    return {
        "efficiency_score": summary.get("efficiencyScore"),
        "size_bytes": summary.get("sizeBytes"),
        "inefficient_bytes": summary.get("inefficientBytes"),
    }


def run_hadolint(dockerfile: Path) -> dict[str, Any]:
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            f"{CONTAINER_PREFIX}hadolint-{dockerfile.parent.name}",
            HADOLINT_IMAGE,
            "hadolint",
            "--format",
            "json",
            "-",
        ],
        input=dockerfile.read_text(),
    )
    # hadolint exits 1 when it finds issues -- that is expected, not a failure.
    try:
        findings = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        findings = []
    return {
        "exit_code": result.returncode,
        "findings_count": len(findings),
        "findings": findings,
    }


def cleanup(tag: str, tarball: Path) -> None:
    _run(["docker", "rmi", "-f", tag])
    for p in [tarball, tarball.parent / f"{tarball.stem}.dive.json"]:
        if p.exists():
            p.unlink()


def measure(repo: str) -> dict[str, Any]:
    repo_dir = REPOS[repo]
    tmp_dir = EVALS_DIR / ".baseline-tmp"
    tmp_dir.mkdir(exist_ok=True)

    tag, tarball, size_bytes, build_seconds = build_image(repo, repo_dir, tmp_dir)
    try:
        trivy_counts = run_trivy(tarball)
        dive_stats = run_dive(tarball)
        hadolint_report = run_hadolint(repo_dir / "Dockerfile")
    finally:
        cleanup(tag, tarball)

    return {
        "repo": repo,
        "image_tag": tag,
        "build_seconds": round(build_seconds, 1),
        "image_size_bytes": size_bytes,
        "trivy": trivy_counts,
        "dive": dive_stats,
        "hadolint": hadolint_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", choices=["e2", "e3"], help="Only measure this repo")
    args = parser.parse_args()

    targets = [args.repo] if args.repo else list(REPOS)
    results: dict[str, Any] = {}
    for repo in targets:
        print(f"=== measuring {repo} ===", file=sys.stderr)
        results[repo] = measure(repo)

    out_path = EVALS_DIR / "baselines.json"
    existing: dict[str, Any] = {}
    if out_path.exists():
        existing = json.loads(out_path.read_text())
    existing.update(results)
    existing["_meta"] = {
        "trivy_image": TRIVY_IMAGE,
        "dive_image": DIVE_IMAGE,
        "hadolint_image": HADOLINT_IMAGE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out_path}", file=sys.stderr)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
