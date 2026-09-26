"""Tests for evals/chaos.py's pure control-flow helpers, against a fake
worker process and a mocked API client (no live worker or Docker needed).
"""

from __future__ import annotations

import sys

import httpx
import pytest
from chaos import _wait_for_step_started, run_chaos
from client import PortPilotClient


def _make_client(handler) -> PortPilotClient:
    client = PortPilotClient("http://fake-api", token="test-token")
    client._client = httpx.Client(
        base_url="http://fake-api",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    )
    return client


def test_wait_for_step_started_finds_matching_event():
    events = [
        {"seq": 1, "type": "step_planned", "payload": {}},
        {"seq": 2, "type": "step_started", "payload": {"seq": 1}},
        {"seq": 3, "type": "step_started", "payload": {"seq": 2}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"events": events, "next_after_seq": 3})

    client = _make_client(handler)
    found = _wait_for_step_started(client, "run_1", seq_min=2, timeout_s=1, poll_interval_s=0.01)
    assert found["payload"]["seq"] == 2


def test_wait_for_step_started_times_out_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"events": [], "next_after_seq": 0})

    client = _make_client(handler)
    with pytest.raises(TimeoutError):
        _wait_for_step_started(client, "run_1", seq_min=2, timeout_s=0.05, poll_interval_s=0.01)


def test_run_chaos_kills_and_restarts_worker_then_returns_metrics():
    """Uses `sys.executable -c 'import time; time.sleep(60)'` as a fake long-lived
    worker so no real portpilot worker binary is needed."""
    fake_worker_cmd = [sys.executable, "-c", "import time; time.sleep(60)"]

    state = {"run_calls": 0}
    events = [{"seq": 1, "type": "step_started", "payload": {"seq": 2}}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/runs/run_1/events":
            return httpx.Response(200, json={"events": events, "next_after_seq": 1})
        if request.url.path == "/api/runs/run_1":
            state["run_calls"] += 1
            status = "running" if state["run_calls"] == 1 else "completed"
            return httpx.Response(
                200,
                json={
                    "run": {"run_id": "run_1", "status": status},
                    "plan": None,
                    "steps": []
                    if status == "running"
                    else [{"step_id": "s1", "status": "done", "usage": {}}],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = _make_client(handler)
    metrics = run_chaos(
        client,
        "run_1",
        fake_worker_cmd,
        step_started_seq_min=2,
        wait_for_step_timeout_s=5,
        poll_interval_s=0.01,
        restart_wait_s=5,
    )
    assert metrics["status"] == "completed"
    assert metrics["steps_done"] == 1
