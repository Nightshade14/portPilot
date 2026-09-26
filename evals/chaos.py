"""Chaos script (MVP_PLAN §8, Lane E): start the worker, kill it mid-STP,
restart it, and assert the Sync 4 conditions (MVP_PLAN §7).

The `portpilot worker` command is built by Lane P and will not exist until
that lane lands; this script is written against that expected CLI surface
and is exercised by tests/evals/test_chaos.py with a fake worker binary, so
it can be validated (import + control flow) before Lane P merges. Running
it for real against the actual worker is a Sync 4 integration step, not
something Lane E's own "Done" check requires.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from typing import Any

from client import PortPilotClient
from scenarios import extract_metrics


def run_chaos(
    client: PortPilotClient,
    run_id: str,
    worker_cmd: list[str],
    *,
    step_started_seq_min: int = 2,
    wait_for_step_timeout_s: float = 120.0,
    poll_interval_s: float = 1.0,
    restart_wait_s: float = 60.0,
) -> dict[str, Any]:
    """Starts `worker_cmd` as a subprocess, waits for a step_started event
    with seq >= step_started_seq_min on run_id, SIGKILLs the worker,
    restarts it, waits for the run to reach a terminal status, and returns
    its metrics (for check_sync4 in evals/assertions.py).
    """
    worker = subprocess.Popen(worker_cmd)
    try:
        _wait_for_step_started(
            client, run_id, step_started_seq_min, wait_for_step_timeout_s, poll_interval_s
        )

        worker.send_signal(signal.SIGKILL)
        worker.wait(timeout=30)

        worker = subprocess.Popen(worker_cmd)
        deadline = time.monotonic() + restart_wait_s
        while True:
            state = client.get_run(run_id)
            run_doc = state["run"]
            if run_doc.get("status") in ("completed", "failed", "cancelled"):
                steps = state.get("steps") or []
                events = client.iter_all_events(run_id)
                return extract_metrics(run_id, run_doc, steps, events)
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"run {run_id} did not reach a terminal status within "
                    f"{restart_wait_s}s of restart (status={run_doc.get('status')!r})"
                )
            time.sleep(poll_interval_s)
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()


def _wait_for_step_started(
    client: PortPilotClient,
    run_id: str,
    seq_min: int,
    timeout_s: float,
    poll_interval_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    after_seq = 0
    while True:
        page = client.get_events(run_id, after_seq=after_seq)
        for event in page["events"]:
            if (
                event.get("type") == "step_started"
                and (event.get("payload") or {}).get("seq", -1) >= seq_min
            ):
                return event
        after_seq = page["next_after_seq"]
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"no step_started event with seq >= {seq_min} within {timeout_s}s for run {run_id}"
            )
        time.sleep(poll_interval_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--worker-cmd", nargs="+", default=["uv", "run", "portpilot", "worker"])
    parser.add_argument("--step-seq-min", type=int, default=2)
    args = parser.parse_args()

    with PortPilotClient(args.base_url, args.token) as client:
        metrics = run_chaos(
            client, args.run_id, args.worker_cmd, step_started_seq_min=args.step_seq_min
        )
    print(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
