"""Worker tests per lane-p.md: claim/heartbeat/release, lost lease, exception ->
failed, reclaim after lease expiry, graceful SIGTERM in a subprocess."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from portpilot.core.fakes import InMemoryRunStore
from portpilot.core.interfaces import RunStore
from portpilot.core.models import Run
from portpilot.worker.main import Worker


@dataclass
class FakeDeps:
    run_store: RunStore
    lease_lost: threading.Event | None = None


def make_worker(run_store: RunStore, run_fn, worker_id: str = "w1", lease_s: int = 60) -> Worker:
    class Settings:
        pass

    settings = Settings()
    settings.worker_id = worker_id  # type: ignore[attr-defined]
    settings.lease_seconds = lease_s  # type: ignore[attr-defined]
    return Worker(
        settings, build_deps=lambda: FakeDeps(run_store=run_store), run_fn=run_fn, poll_s=0.05
    )


def _seed_run(store: InMemoryRunStore, run_id: str = "run_1") -> None:
    store.create_run(Run(run_id=run_id, repo_url="https://github.com/a/b", goal="migrate"))


def test_claims_heartbeats_and_releases() -> None:
    store = InMemoryRunStore()
    _seed_run(store)
    seen_lease_lost: list[bool] = []

    def run_fn(deps: FakeDeps, run_id: str, worker_id: str) -> None:
        time.sleep(0.2)
        seen_lease_lost.append(deps.lease_lost.is_set())

    worker = make_worker(store, run_fn, lease_s=1)  # heartbeat every 0.25s
    claimed = worker._try_claim_and_run(store)
    assert claimed is True
    assert seen_lease_lost == [False]
    run = store.get_run("run_1")
    assert run.lease is None  # released


def test_lost_lease_sets_event_and_run_fn_can_observe_it() -> None:
    store = InMemoryRunStore()
    _seed_run(store)
    observed = threading.Event()

    def run_fn(deps: FakeDeps, run_id: str, worker_id: str) -> None:
        # Simulate another worker stealing the lease mid-run.
        store.release(run_id, worker_id)
        store._runs[run_id].lease = None
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if deps.lease_lost.is_set():
                observed.set()
                return
            time.sleep(0.05)

    worker = make_worker(
        store, run_fn, lease_s=1
    )  # heartbeat every 0.25s; heartbeat() -> False once lease is gone
    # Force heartbeat() to report lost by clearing the lease's owner mismatch:
    # emulate by monkeypatching heartbeat to return False after first release.
    original_heartbeat = store.heartbeat

    def flaky_heartbeat(run_id: str, worker_id: str, lease_s: int = 60) -> bool:
        run = store._runs.get(run_id)
        if run is None or run.lease is None:
            return False
        return original_heartbeat(run_id, worker_id, lease_s)

    store.heartbeat = flaky_heartbeat  # type: ignore[method-assign]

    worker._try_claim_and_run(store)
    assert observed.is_set()


def test_exception_in_run_fn_marks_run_failed() -> None:
    store = InMemoryRunStore()
    _seed_run(store)

    def run_fn(deps: FakeDeps, run_id: str, worker_id: str) -> None:
        raise ValueError("boom")

    worker = make_worker(store, run_fn)
    worker._try_claim_and_run(store)

    run = store.get_run("run_1")
    assert run.status == "failed"
    assert run.error == "boom"
    events = store.events("run_1")
    assert any(e["type"] == "failed" for e in events)
    assert run.lease is None  # still released


def test_second_worker_reclaims_after_lease_expires() -> None:
    store = InMemoryRunStore()
    _seed_run(store)

    # Worker A claims with a 0-second lease that is already expired by the time B looks.
    run = store.claim_run("worker-a", lease_s=0)
    assert run is not None
    time.sleep(0.05)

    reclaimed = store.claim_run("worker-b", lease_s=60)
    assert reclaimed is not None
    assert reclaimed.run_id == "run_1"
    assert reclaimed.lease.owner == "worker-b"


def test_no_queued_or_expired_run_returns_false() -> None:
    store = InMemoryRunStore()

    def run_fn(deps: FakeDeps, run_id: str, worker_id: str) -> None:  # pragma: no cover
        raise AssertionError("should not be called")

    worker = make_worker(store, run_fn)
    claimed = worker._try_claim_and_run(store)
    assert claimed is False


def test_graceful_sigterm_subprocess(tmp_path) -> None:
    """SIGTERM stops claiming and lets the current run finish; run completes normally."""
    import subprocess
    import sys

    script = tmp_path / "worker_sigterm.py"
    marker = tmp_path / "run_started"
    finished = tmp_path / "run_finished"
    script.write_text(
        f"""
import signal
import time
from dataclasses import dataclass

from portpilot.core.fakes import InMemoryRunStore
from portpilot.core.models import Run
from portpilot.worker.main import Worker


@dataclass
class Deps:
    run_store: object
    lease_lost: object = None


store = InMemoryRunStore()
store.create_run(Run(run_id="run_1", repo_url="https://github.com/a/b", goal="migrate"))


def run_fn(deps, run_id, worker_id):
    open({str(marker)!r}, "w").close()
    time.sleep(1.5)
    open({str(finished)!r}, "w").close()


class Settings:
    worker_id = "w1"
    lease_seconds = 30


worker = Worker(Settings(), build_deps=lambda: Deps(run_store=store), run_fn=run_fn, poll_s=0.1)
worker.install_signal_handlers()
worker.run_forever(run_store=store)
"""
    )
    proc = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "worker never started the run"

        proc.send_signal(__import__("signal").SIGTERM)
        proc.wait(timeout=10)
        assert finished.exists(), "SIGTERM should let the in-flight run finish"
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
