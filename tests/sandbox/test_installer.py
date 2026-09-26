"""`docker` marker: DockerCliInstaller (allow-listed CLI installs) against a real
container. Uses `jq` (small, fast binary download) as the representative real
install; also exercises trivial refusals that don't need a download.
"""

from __future__ import annotations

import copy

import pytest

from portpilot.sandbox.installer import DockerCliInstaller

pytestmark = [pytest.mark.docker, pytest.mark.network]


@pytest.fixture
def installer(manager):
    return DockerCliInstaller(manager)


def test_refuses_unknown_tool_name(manager, installer, run_id):
    manager.ensure(run_id)

    result = installer.install(run_id, "totally-not-a-tool")

    assert result.ok is False
    assert result.refused is True
    assert "not in the allow-list" in result.reason


def test_refuses_tool_with_no_published_sha256(manager, installer, run_id):
    manager.ensure(run_id)

    result = installer.install(run_id, "shellcheck")

    assert result.ok is False
    assert result.refused is True
    assert "sha256" in result.reason


def test_installs_a_real_tool_and_is_idempotent(manager, installer, run_id):
    manager.ensure(run_id)

    first = installer.install(run_id, "jq")
    assert first.ok is True
    assert first.already_installed is False

    verify = manager.exec(run_id, "jq --version", cwd="/")
    assert verify.exit_code == 0
    assert "jq-" in verify.stdout

    second = installer.install(run_id, "jq")
    assert second.ok is True
    assert second.already_installed is True


def test_refuses_checksum_mismatch(manager, installer, run_id):
    manager.ensure(run_id)
    orig_allowlist = installer.allowlist

    def tampered():
        data = copy.deepcopy(orig_allowlist())
        for arch_entry in data["jq"]["architectures"].values():
            arch_entry["sha256"] = "0" * 64
        return data

    installer.allowlist = tampered
    try:
        result = installer.install(run_id, "jq")
    finally:
        installer.allowlist = orig_allowlist

    assert result.ok is False
    assert result.refused is True
    assert "checksum mismatch" in result.reason


def test_check_environment_reports_expected_shape(manager, installer, run_id):
    manager.ensure(run_id)

    report = installer.check_environment(run_id)

    assert report["os"] == "linux"
    assert report["arch"] in ("aarch64", "x86_64")
    assert isinstance(report["disk_free_mb"], int)
    assert isinstance(report["mem_mb"], int)
    assert isinstance(report["installed"], dict)
    assert isinstance(report["repo_languages"], dict)
    assert "jq" in report["allowlisted"]
    assert "trivy" in report["allowlisted"]
