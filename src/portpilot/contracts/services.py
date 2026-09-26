"""Service process management. Owner: Lane A.

Starts the Flask source and a Hono target directory as subprocesses on
127.0.0.1 only, waits for GET /health, and tears them down cleanly.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from portpilot.config import FIXTURE_DIR

HEALTH_PATH = "/health"


def free_port() -> int:
    """Return an OS-assigned free TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, proc: subprocess.Popen, timeout: float, label: str) -> None:
    """Poll {base_url}/health until 200 or timeout. Raise on failure/exit."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise _boot_error(label, proc, f"process exited early with code {proc.returncode}")
        try:
            resp = httpx.get(f"{base_url}{HEALTH_PATH}", timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:  # not up yet
            last_error = exc
        time.sleep(0.1)
    raise _boot_error(label, proc, f"health check timed out after {timeout:.0f}s: {last_error}")


def _boot_error(label: str, proc: subprocess.Popen, why: str) -> RuntimeError:
    """Build a clear error including the tail of the process's stderr."""
    tail = ""
    if proc.stderr is not None:
        try:
            proc.stderr.flush()
        except Exception:  # noqa: BLE001, S110 - best effort, tail may be partial
            pass
        try:
            data = proc.stderr.read() or ""
        except Exception:  # noqa: BLE001 - best effort
            data = ""
        tail = "\n".join(data.splitlines()[-30:])
    return RuntimeError(f"{label} failed to boot: {why}\n--- stderr tail ---\n{tail}")


@contextmanager
def flask_source(port: int | None = None, source_dir: Path = FIXTURE_DIR) -> Iterator[str]:
    """Yield the source base URL, e.g. http://127.0.0.1:5001."""
    port = port or free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(port)],
        cwd=str(source_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_health(base_url, proc, timeout=10.0, label="flask source")
        yield base_url
    finally:
        _terminate(proc, group=False)


@contextmanager
def hono_target(target_dir: Path, port: int | None = None) -> Iterator[str]:
    """Run `npx tsx src/index.ts` in target_dir with PORT set; yield base URL."""
    port = port or free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PORT": str(port)}
    proc = subprocess.Popen(
        ["npx", "tsx", "src/index.ts"],
        cwd=str(target_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # own process group so we can kill children (tsx forks node)
    )
    try:
        _wait_for_health(base_url, proc, timeout=20.0, label="hono target")
        yield base_url
    finally:
        _terminate(proc, group=True)


def _terminate(proc: subprocess.Popen, *, group: bool) -> None:
    """Terminate a process (or its group) and wait for it to exit."""
    if proc.poll() is not None:
        return
    try:
        if group:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        try:
            if group:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            return
        proc.wait(timeout=5.0)
