"""Fixtures for tests/sandbox: unique run_ids and guaranteed cleanup of every
container/volume/network this test session creates, prefixed `pp-test-s-` per the
lane brief and docs/plan/mvp-lanes/README.md.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Iterator

import pytest

from portpilot.sandbox.manager import DockerSandboxManager

TEST_CONTAINER_PREFIX = "pp-test-s-sbx-"
TEST_NETWORK = "pp-test-s-net"


def _docker(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=60
    )


@pytest.fixture
def run_id() -> str:
    return f"t{uuid.uuid4().hex[:10]}"


@pytest.fixture
def manager() -> Iterator[DockerSandboxManager]:
    mgr = DockerSandboxManager(
        image="portpilot-sandbox:dev",
        network=TEST_NETWORK,
        allow_local_repos=True,
        container_prefix=TEST_CONTAINER_PREFIX,
    )
    created: list[str] = []
    orig_ensure = mgr.ensure

    def tracked_ensure(rid: str, repo_url: str | None = None) -> str:
        created.append(rid)
        return orig_ensure(rid, repo_url)

    mgr.ensure = tracked_ensure  # type: ignore[method-assign]

    yield mgr

    for rid in created:
        mgr.destroy(rid)


@pytest.fixture
def local_repo(tmp_path):
    """A tiny git repo on the host, for `allow_local_repos=True` tests -- avoids
    needing network access for the core `docker` marker suite."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    for args in (
        ["init", "-q"],
        ["-c", "user.email=t@t.com", "-c", "user.name=t", "add", "-A"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo
