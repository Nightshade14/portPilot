"""Tests for evals/scenarios.py: run_scenario end to end (via httpx.MockTransport)
and extract_metrics directly against synthetic event streams.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from client import PortPilotClient
from scenarios import extract_metrics, run_scenario


def _make_client(handler) -> PortPilotClient:
    """Build a PortPilotClient whose httpx.Client is wired to a MockTransport."""
    client = PortPilotClient("http://fake-api", token="test-token")
    client._client = httpx.Client(
        base_url="http://fake-api",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    )
    return client


def _run_doc(run_id: str, status: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "repo_url": "https://github.com/example/repo",
        "goal": "do the thing",
        "status": status,
        "created_at": "2026-09-26T18:00:00+00:00",
        "updated_at": "2026-09-26T18:05:00+00:00",
    }


def _step_doc(step_id: str, status: str, tokens: int) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "run_id": "run_1",
        "seq": 1,
        "phase_id": "phase_1",
        "title": "a step",
        "objective": "do part of the thing",
        "status": status,
        "usage": {"input_tokens": tokens, "output_tokens": tokens // 2},
    }


def test_run_scenario_polls_to_terminal_status_and_extracts_metrics():
    """First get_run returns 'running'; second returns 'completed'. Events
    include a tools_selected, a tool_created, a compaction and a lesson."""
    state = {"calls": 0}

    events = [
        {
            "run_id": "run_1",
            "seq": 1,
            "ts": "2026-09-26T18:00:01+00:00",
            "type": "step_started",
            "step_id": "step_1",
            "payload": {"seq": 1, "title": "a step", "attempt": 1},
        },
        {
            "run_id": "run_1",
            "seq": 2,
            "ts": "2026-09-26T18:00:02+00:00",
            "type": "tools_selected",
            "step_id": "step_1",
            "payload": {
                "candidates": [],
                "picks": [{"name": "http_contract_diff", "version": 1, "reason": "reuse"}],
                "missing": [],
                "core_tools": ["shell"],
                "tool_schema_tokens": 500,
            },
        },
        {
            "run_id": "run_1",
            "seq": 3,
            "ts": "2026-09-26T18:00:03+00:00",
            "type": "tool_created",
            "step_id": "step_1",
            "payload": {
                "name": "http_contract_diff",
                "version": 1,
                "purpose": "diff HTTP responses",
            },
        },
        {
            "run_id": "run_1",
            "seq": 4,
            "ts": "2026-09-26T18:00:04+00:00",
            "type": "compaction",
            "step_id": "step_1",
            "payload": {
                "tokens_before": 100000,
                "tokens_after": 20000,
                "messages_before": 80,
                "messages_after": 10,
            },
        },
        {
            "run_id": "run_1",
            "seq": 5,
            "ts": "2026-09-26T18:00:05+00:00",
            "type": "lesson_recorded",
            "step_id": "step_1",
            "payload": {"item_id": "lesson_1", "title": "a lesson", "merged": False},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/runs/run_1" and request.method == "GET":
            state["calls"] += 1
            status = "running" if state["calls"] == 1 else "completed"
            steps = (
                []
                if status == "running"
                else [_step_doc("step_1", "done", 1000), _step_doc("step_2", "done", 2000)]
            )
            return httpx.Response(
                200, json={"run": _run_doc("run_1", status), "plan": None, "steps": steps}
            )
        if request.url.path == "/api/runs/run_1/events" and request.method == "GET":
            after_seq = int(request.url.params.get("after_seq", "0"))
            batch = [e for e in events if e["seq"] > after_seq]
            next_after_seq = batch[-1]["seq"] if batch else after_seq
            return httpx.Response(200, json={"events": batch, "next_after_seq": next_after_seq})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _make_client(handler)

    def fake_create_run(repo_url, goal, budgets=None):
        return "run_1"

    client.create_run = fake_create_run  # avoid a POST /api/runs branch in handler

    metrics = run_scenario(
        client, "https://github.com/example/repo", "do the thing", timeout_s=10, poll_interval_s=0
    )

    assert metrics["run_id"] == "run_1"
    assert metrics["status"] == "completed"
    assert metrics["steps_total"] == 2
    assert metrics["steps_done"] == 2
    assert metrics["steps_failed"] == 0
    assert metrics["tokens_per_step"] == {"step_1": 1500, "step_2": 3000}
    assert metrics["tool_schema_tokens_per_step"] == {"step_1": 500}
    assert len(metrics["tools_created"]) == 1
    assert metrics["tools_created"][0]["name"] == "http_contract_diff"
    assert len(metrics["compactions"]) == 1
    assert metrics["compactions"][0]["tokens_before"] == 100000
    assert metrics["lessons_recorded"] == 1
    assert metrics["gotchas_recorded"] == 0


def test_run_scenario_times_out_when_never_terminal():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/runs/run_1":
            return httpx.Response(
                200, json={"run": _run_doc("run_1", "running"), "plan": None, "steps": []}
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _make_client(handler)
    client.create_run = lambda *a, **k: "run_1"

    with pytest.raises(TimeoutError):
        run_scenario(
            client, "https://github.com/example/repo", "goal", timeout_s=0.05, poll_interval_s=0.01
        )


def test_extract_metrics_flags_tool_reused_from_a_different_run():
    run_doc = _run_doc("run_2", "completed")
    steps = [_step_doc("step_1", "done", 100)]
    events = [
        {
            "run_id": "run_2",
            "seq": 1,
            "ts": "2026-09-26T18:00:00+00:00",
            "type": "tools_selected",
            "step_id": "step_1",
            "payload": {
                "candidates": [],
                "picks": [
                    {
                        "name": "http_contract_diff",
                        "version": 1,
                        "reason": "reuse from run_1",
                        "provenance": {"run_id": "run_1"},
                    }
                ],
                "missing": [],
                "core_tools": [],
                "tool_schema_tokens": 300,
            },
        }
    ]
    metrics = extract_metrics("run_2", run_doc, steps, events)
    assert len(metrics["tools_reused"]) == 1
    assert metrics["tools_reused"][0]["name"] == "http_contract_diff"


def test_extract_metrics_counts_cli_installs_and_refusals():
    run_doc = _run_doc("run_1", "completed")
    steps = [_step_doc("step_1", "done", 100)]
    events = [
        {
            "run_id": "run_1",
            "seq": 1,
            "ts": "2026-09-26T18:00:00+00:00",
            "type": "cli_installed",
            "step_id": "step_1",
            "payload": {"name": "trivy", "version": "0.74.0", "already_installed": False},
        },
        {
            "run_id": "run_1",
            "seq": 2,
            "ts": "2026-09-26T18:00:01+00:00",
            "type": "cli_refused",
            "step_id": "step_1",
            "payload": {"name": "shellcheck", "reason": "not in allow-list"},
        },
        {
            "run_id": "run_1",
            "seq": 3,
            "ts": "2026-09-26T18:00:02+00:00",
            "type": "gotcha_recorded",
            "step_id": "step_1",
            "payload": {"item_id": "g1", "title": "a gotcha", "merged": True},
        },
    ]
    metrics = extract_metrics("run_1", run_doc, steps, events)
    assert len(metrics["cli_installed"]) == 1
    assert len(metrics["cli_refused"]) == 1
    assert metrics["gotchas_recorded"] == 1


def test_iter_all_events_pages_until_no_progress():
    pages = [
        {"events": [{"seq": 1}, {"seq": 2}], "next_after_seq": 2},
        {"events": [{"seq": 3}], "next_after_seq": 3},
        {"events": [], "next_after_seq": 3},
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    client = _make_client(handler)
    events = client.iter_all_events("run_1")
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert calls["n"] == 3  # keeps paging until a page's next_after_seq stalls


def test_client_health_and_run_lifecycle_calls():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True, "version": "0.1.0"})
        if request.url.path.endswith("/pause"):
            return httpx.Response(200, json={"ok": True, "status": "paused"})
        if request.url.path.endswith("/resume"):
            return httpx.Response(200, json={"ok": True, "status": "queued"})
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"ok": True, "status": "cancelled"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _make_client(handler)
    assert client.health() == {"ok": True, "version": "0.1.0"}
    assert client.pause_run("run_1")["status"] == "paused"
    assert client.resume_run("run_1")["status"] == "queued"
    assert client.cancel_run("run_1")["status"] == "cancelled"
    assert ("GET", "/api/health") in seen
