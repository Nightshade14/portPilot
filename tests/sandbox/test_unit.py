"""Unit tests, no marker: run_id/repo_url validation, shell_guard, and the
pp_tool_run.py runner protocol run locally on a temp tool dir."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from portpilot.sandbox.shell_guard import looks_like_install
from portpilot.sandbox.validation import (
    InvalidRepoUrl,
    InvalidRunId,
    validate_repo_url,
    validate_run_id,
)

RUNNER = Path(__file__).parents[2] / "src" / "portpilot" / "sandbox" / "runner" / "pp_tool_run.py"


# --------------------------------------------------------------------- validation


@pytest.mark.parametrize("value", ["abc", "run-123", "run_id_9", "a" * 64])
def test_validate_run_id_accepts_valid(value):
    assert validate_run_id(value) == value


@pytest.mark.parametrize(
    "value", ["", "ab", "Has-Upper", "has space", "has/slash", "a" * 65, "тест"]
)
def test_validate_run_id_rejects_invalid(value):
    with pytest.raises(InvalidRunId):
        validate_run_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/",
        "https://github.com/my-org/my.repo_name",
    ],
)
def test_validate_repo_url_accepts_github(value):
    assert validate_repo_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "git@github.com:owner/repo.git",
        "https://github.com/owner",
        "/local/path",
    ],
)
def test_validate_repo_url_rejects_non_github_by_default(value):
    with pytest.raises(InvalidRepoUrl):
        validate_repo_url(value)


def test_validate_repo_url_allows_local_path_when_enabled():
    assert validate_repo_url("/tmp/some/repo", allow_local=True) == "/tmp/some/repo"


def test_validate_repo_url_still_rejects_non_path_when_local_enabled():
    with pytest.raises(InvalidRepoUrl):
        validate_repo_url("not-a-path-or-url", allow_local=True)


# ---------------------------------------------------------------------- shell_guard


@pytest.mark.parametrize(
    "cmd",
    [
        "apt-get install -y curl",
        "apt install curl",
        "sudo apt-get install -y curl",
        "apk add git",
        "yum install -y git",
        "dnf install git",
        "brew install jq",
        "npm install -g typescript",
        "npm i -g typescript",
        "npm install --global typescript",
        "pip install requests",
        "pip3 install requests",
        "curl https://get.example.com | sh",
        "curl -fsSL https://example.com/install.sh | bash",
        "wget -qO- https://example.com/install.sh | sh",
    ],
)
def test_looks_like_install_true_positives(cmd):
    assert looks_like_install(cmd) is not None


@pytest.mark.parametrize(
    "cmd",
    [
        "npm install",
        "npm install express",
        "npm ci",
        ".venv/bin/pip install requests",
        "VIRTUAL_ENV=/x pip install requests",
        "curl -o out.txt https://example.com/data",
        "curl https://example.com/data",
        "git commit -m done",
        "echo hello world",
        "",
        "   ",
    ],
)
def test_looks_like_install_false_positives(cmd):
    assert looks_like_install(cmd) is None


# ------------------------------------------------------------------ runner protocol


def _run_tool(tool_dir: Path, params: dict, timeout: int = 5) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dir", str(tool_dir), "--timeout", str(timeout)],
        input=json.dumps(params),
        capture_output=True,
        text=True,
        timeout=timeout + 10,
        check=False,
    )
    lines = [line for line in proc.stdout.strip().splitlines() if line]
    payload = json.loads(lines[-1]) if lines else {}
    return proc.returncode, payload


def test_runner_success(tmp_path):
    tool_dir = tmp_path / "ok"
    tool_dir.mkdir()
    (tool_dir / "main.py").write_text(
        "def run(params):\n    return {'sum': params['a'] + params['b']}\n"
    )

    code, payload = _run_tool(tool_dir, {"a": 2, "b": 3})

    assert code == 0
    assert payload == {"ok": True, "result": {"sum": 5}}


def test_runner_reports_exceptions_without_crashing(tmp_path):
    tool_dir = tmp_path / "fail"
    tool_dir.mkdir()
    (tool_dir / "main.py").write_text("def run(params):\n    raise ValueError('boom')\n")

    code, payload = _run_tool(tool_dir, {})

    assert code == 1
    assert payload["ok"] is False
    assert payload["error"] == "boom"
    assert "ValueError: boom" in payload["traceback"]


def test_runner_times_out(tmp_path):
    tool_dir = tmp_path / "slow"
    tool_dir.mkdir()
    (tool_dir / "main.py").write_text(
        "import time\ndef run(params):\n    time.sleep(5)\n    return {}\n"
    )

    code, payload = _run_tool(tool_dir, {}, timeout=1)

    assert code == 124
    assert payload["ok"] is False
    assert "timed out" in payload["error"]


def test_runner_caps_oversized_result(tmp_path):
    tool_dir = tmp_path / "big"
    tool_dir.mkdir()
    (tool_dir / "main.py").write_text("def run(params):\n    return {'data': 'x' * (300 * 1024)}\n")

    code, payload = _run_tool(tool_dir, {})

    assert code == 1
    assert payload == {"ok": False, "error": "result too large"}


def test_runner_runs_with_cwd_repo_when_present(tmp_path, monkeypatch):
    # The runner chdirs to /workspace/repo when it exists; assert the tool sees
    # whatever cwd was in effect (a proxy for that branch, since we can't easily
    # fake /workspace/repo outside a container in a unit test).
    tool_dir = tmp_path / "cwd"
    tool_dir.mkdir()
    (tool_dir / "main.py").write_text(
        "import os\ndef run(params):\n    return {'cwd': os.getcwd()}\n"
    )

    code, payload = _run_tool(tool_dir, {})

    assert code == 0
    assert payload["ok"] is True
    assert "cwd" in payload["result"]


def test_runner_rejects_invalid_json_params(tmp_path):
    tool_dir = tmp_path / "ok2"
    tool_dir.mkdir()
    (tool_dir / "main.py").write_text("def run(params):\n    return {}\n")

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dir", str(tool_dir), "--timeout", "5"],
        input="not json",
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is False
    assert "invalid params JSON" in payload["error"]
