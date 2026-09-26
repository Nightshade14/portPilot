"""End-to-end smoke: start `portpilot api` (in-memory stores, insecure dev), create a
run through httpx, read it back."""

from __future__ import annotations

import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.network
def test_smoke_api_create_and_read_run(tmp_path) -> None:
    port = 8765
    env = {
        "PORTPILOT_API_INSECURE_DEV": "1",
        "PORTPILOT_MVP_STORE": "memory",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "portpilot.cli", "api", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 15
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{base}/api/health", timeout=1)
                if resp.status_code == 200:
                    break
            except httpx.HTTPError as exc:
                last_exc = exc
            time.sleep(0.3)
        else:
            raise AssertionError(f"server never became healthy: {last_exc}")

        create = httpx.post(
            f"{base}/api/runs",
            json={"repo_url": "https://github.com/octocat/hello-world", "goal": "smoke test run"},
            timeout=5,
        )
        assert create.status_code == 201, create.text
        run_id = create.json()["run_id"]

        got = httpx.get(f"{base}/api/runs/{run_id}", timeout=5)
        assert got.status_code == 200
        assert got.json()["run"]["run_id"] == run_id
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
