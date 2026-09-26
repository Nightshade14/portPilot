"""Validation helpers shared across the sandbox package."""

from __future__ import annotations

import re

RUN_ID_RE = re.compile(r"^[a-z0-9_-]{3,64}$")

# Same shape as docs/api/CONTRACT.md's `repo_url` validation, plus a bare local
# path (checked separately by callers that pass allow_local_repos=True).
REPO_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?/?$")


class InvalidRunId(ValueError):
    pass


class InvalidRepoUrl(ValueError):
    pass


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise InvalidRunId(f"run_id {run_id!r} does not match {RUN_ID_RE.pattern}")
    return run_id


def validate_repo_url(repo_url: str, *, allow_local: bool = False) -> str:
    if REPO_URL_RE.match(repo_url):
        return repo_url
    if allow_local and repo_url.startswith("/"):
        return repo_url
    raise InvalidRepoUrl(f"repo_url {repo_url!r} does not match {REPO_URL_RE.pattern}")
