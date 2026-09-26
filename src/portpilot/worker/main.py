"""`Worker`: claims runs, drives run_fn, heartbeats the lease, releases (lane-p.md).

Shutdown: SIGTERM/SIGINT stop claiming new runs and let the current run reach its
next checkpoint before exiting; a second signal exits immediately (the lease then
expires on its own and another worker reclaims the run).
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from types import FrameType
from typing import Any, Protocol

from portpilot.core.config import MvpSettings
from portpilot.core.interfaces import RunStore

logger = logging.getLogger(__name__)


class RunFnDeps(Protocol):
    """What `run_fn` receives: build_deps()'s return value, plus lease_lost."""

    lease_lost: threading.Event


class Worker:
    def __init__(
        self,
        settings: MvpSettings,
        build_deps: Callable[[], Any],
        run_fn: Callable[[Any, str, str], None],
        poll_s: float = 3,
    ) -> None:
        self.settings = settings
        self.build_deps = build_deps
        self.run_fn = run_fn
        self.poll_s = poll_s
        self.worker_id = settings.worker_id
        self.lease_s = settings.lease_seconds

        self._stop_claiming = threading.Event()
        self._force_exit = threading.Event()
        self._sigterm_count = 0

    # ------------------------------------------------------------- lifecycle

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        self._sigterm_count += 1
        if self._sigterm_count == 1:
            logger.warning("received signal %s: stopping claims, finishing current run", signum)
            self._stop_claiming.set()
        else:
            logger.warning("received second signal %s: exiting immediately", signum)
            self._force_exit.set()

    def run_forever(self, run_store: RunStore | None = None) -> None:
        """Poll-claim-run loop. `run_store` lets callers (tests) share a store instance
        with `build_deps`; when omitted, each cycle's deps supply their own."""
        while not self._stop_claiming.is_set() and not self._force_exit.is_set():
            claimed = self._try_claim_and_run(run_store)
            if not claimed:
                time.sleep(self.poll_s)

    def _try_claim_and_run(self, run_store: RunStore | None) -> bool:
        deps = self.build_deps()
        store: RunStore = run_store if run_store is not None else _extract_run_store(deps)
        run = store.claim_run(self.worker_id, lease_s=self.lease_s)
        if run is None:
            return False
        store.log_event(run.run_id, "lease_acquired", payload={"worker_id": self.worker_id})
        self._drive_run(deps, store, run.run_id)
        return True

    def _drive_run(self, deps: Any, store: RunStore, run_id: str) -> None:
        lease_lost = threading.Event()
        try:
            deps.lease_lost = lease_lost
        except AttributeError:
            pass

        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(store, run_id, lease_lost, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            self.run_fn(deps, run_id, self.worker_id)
        except Exception as exc:
            logger.exception("run_fn raised for run %s", run_id)
            try:
                store.update_run(run_id, status="failed", error=str(exc))
                store.log_event(run_id, "failed", payload={"reason": str(exc)})
            except Exception:  # pragma: no cover - store itself is unhealthy
                logger.exception("failed to record failure for run %s", run_id)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=self.lease_s)
            try:
                store.release(run_id, self.worker_id)
            except Exception:  # pragma: no cover
                logger.exception("failed to release run %s", run_id)

    def _heartbeat_loop(
        self,
        store: RunStore,
        run_id: str,
        lease_lost: threading.Event,
        stop: threading.Event,
    ) -> None:
        interval = max(self.lease_s / 4, 0.1)
        while not stop.wait(interval):
            ok = store.heartbeat(run_id, self.worker_id, lease_s=self.lease_s)
            if not ok:
                logger.warning("lease lost for run %s (worker %s)", run_id, self.worker_id)
                lease_lost.set()
                return


def _extract_run_store(deps: Any) -> RunStore:
    run_store = getattr(deps, "run_store", None)
    if run_store is None:
        raise AttributeError("build_deps() must return an object with a `run_store` attribute")
    return run_store


def main() -> None:
    """Entry point for `portpilot worker`. Imports `agent.loop.run_migration` lazily
    (Lane A); exits with a clear message if that package isn't available yet."""
    logging.basicConfig(level=logging.INFO)
    from portpilot.core.config import load_mvp_settings

    settings = load_mvp_settings()

    try:
        from portpilot.agent.loop import run_migration  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "portpilot.agent.loop.run_migration is not available yet (Lane A). "
            f"Underlying import error: {exc}"
        ) from exc

    from portpilot.agent.runtime import build_agent_deps

    def build_deps() -> Any:
        return build_agent_deps(settings)

    worker = Worker(settings, build_deps, run_migration, poll_s=3)
    worker.install_signal_handlers()
    worker.run_forever()


if __name__ == "__main__":
    main()
