"""`docker` marker: DockerSandboxManager against a real Docker daemon.

Uses `allow_local_repos=True` with a local fixture repo, so no network access is
needed (per the brief: "For `ensure`, use `allow_local_repos` with a local test
repo, so no network is needed.").
"""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.docker


def test_ensure_creates_container_and_clones_local_repo(manager, run_id, local_repo):
    container = manager.ensure(run_id, repo_url=str(local_repo))

    assert container == manager._container(run_id)
    result = manager.exec(run_id, "git rev-parse --abbrev-ref HEAD")
    assert result.exit_code == 0
    assert result.stdout.strip() == f"portpilot/{run_id}"

    readme = manager.read_file(run_id, "/workspace/repo/README.md")
    assert readme == "hello\n"


def test_ensure_is_idempotent(manager, run_id, local_repo):
    c1 = manager.ensure(run_id, repo_url=str(local_repo))
    c2 = manager.ensure(run_id)
    assert c1 == c2


def test_ensure_reattaches_after_stop_with_volume_intact(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))
    manager.write_file(run_id, "/workspace/repo/marker.txt", "still here\n")
    manager.stop(run_id)

    container = manager.ensure(run_id)

    assert container == manager._container(run_id)
    assert manager.read_file(run_id, "/workspace/repo/marker.txt") == "still here\n"


def test_exec_timeout(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))

    result = manager.exec(run_id, "sleep 5", timeout_s=1)

    assert result.timed_out is True
    assert result.exit_code == 124


def test_exec_caps_output(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))

    result = manager.exec(run_id, "head -c 2000000 /dev/zero | tr '\\0' 'a'")

    assert result.exit_code == 0
    assert len(result.stdout.encode()) <= 1024 * 1024 + len("\n...[truncated]")
    assert result.stdout.endswith("...[truncated]")


def test_write_and_read_file_with_quotes_and_newlines(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))
    content = "line one\nline with 'single' and \"double\" quotes\nline three\n"

    manager.write_file(run_id, "/workspace/repo/quoted.txt", content)
    result = manager.read_file(run_id, "/workspace/repo/quoted.txt")

    assert result == content


def test_commit_and_restore_round_trip(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))

    manager.write_file(run_id, "/workspace/repo/a.txt", "v1\n")
    sha1 = manager.commit(run_id, "add a.txt")
    assert sha1

    manager.write_file(run_id, "/workspace/repo/a.txt", "v2\n")
    manager.exec(run_id, "echo untracked > /workspace/repo/b.txt")
    sha2 = manager.commit(run_id, "modify a.txt")
    assert sha2 != sha1

    manager.restore(run_id, sha1)

    assert manager.read_file(run_id, "/workspace/repo/a.txt") == "v1\n"
    exists = manager.exec(run_id, "test -f /workspace/repo/b.txt")
    assert exists.exit_code != 0  # untracked file removed by `git clean -fd`


def test_commit_with_nothing_to_commit_returns_head_unchanged(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))
    sha1 = manager.commit(run_id, "first commit call, nothing changed since ensure")

    sha2 = manager.commit(run_id, "second call, still nothing changed")

    assert sha1 == sha2


def test_export_archive_returns_valid_tar_gz(manager, run_id, local_repo, tmp_path):
    manager.ensure(run_id, repo_url=str(local_repo))

    archive = manager.export_archive(run_id)

    out_path = tmp_path / "export.tar.gz"
    out_path.write_bytes(archive)
    proc = subprocess.run(
        ["tar", "-tzf", str(out_path)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0
    assert "README.md" in proc.stdout


def test_destroy_removes_container_and_volumes(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))
    ws_vol = manager._ws_volume(run_id)
    tools_vol = manager._tools_volume(run_id)

    manager.destroy(run_id)

    assert not manager._container_exists(manager._container(run_id))
    vols = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert ws_vol not in vols
    assert tools_vol not in vols
