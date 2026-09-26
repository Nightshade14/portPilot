"""Endpoint coverage per lane-p.md: every route, auth, validation, transitions,
pagination, download, and error shapes for 401/404/409/422/429."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from portpilot.api.app import ApiDeps


def _create_run(client: TestClient, auth_headers: dict[str, str], **overrides) -> str:
    body = {"repo_url": "https://github.com/octocat/hello-world", "goal": "migrate it"}
    body.update(overrides)
    resp = client.post("/api/runs", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["run_id"]


# --------------------------------------------------------------------- health


def test_health_no_auth_required(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "version": "0.1.0"}


# ----------------------------------------------------------------------- auth


def test_every_route_except_health_requires_auth(client: TestClient) -> None:
    routes = [
        ("GET", "/api/runs"),
        ("GET", "/api/runs/run_x"),
        ("GET", "/api/runs/run_x/steps/step_x"),
        ("GET", "/api/runs/run_x/events"),
        ("POST", "/api/runs/run_x/pause"),
        ("POST", "/api/runs/run_x/resume"),
        ("POST", "/api/runs/run_x/cancel"),
        ("GET", "/api/runs/run_x/artifacts"),
        ("GET", "/api/runs/run_x/artifacts/art_x"),
        ("GET", "/api/runs/run_x/download"),
        ("GET", "/api/tools"),
        ("GET", "/api/tools/some_tool"),
        ("GET", "/api/knowledge/search?q=x"),
        ("GET", "/api/knowledge"),
    ]
    for method, path in routes:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} did not require auth"
        assert resp.json() == {
            "error": {"code": "unauthorized", "message": "missing or invalid bearer token"}
        }


def test_wrong_token_is_401(client: TestClient) -> None:
    resp = client.get("/api/runs", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_missing_bearer_prefix_is_401(client: TestClient) -> None:
    resp = client.get("/api/runs", headers={"Authorization": "test-token-123"})
    assert resp.status_code == 401


# -------------------------------------------------------------------- create


def test_create_run_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/runs",
        json={
            "repo_url": "https://github.com/octocat/hello-world",
            "goal": "migrate flask to hono",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body.keys()) == {"run_id"}
    assert body["run_id"].startswith("run_")


def test_create_run_logs_run_created_event(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    events = deps.run_store.events(run_id)
    assert len(events) == 1
    assert events[0]["type"] == "run_created"
    assert events[0]["payload"] == {
        "repo_url": "https://github.com/octocat/hello-world",
        "goal": "migrate it",
    }


def test_create_run_status_is_queued(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    run = deps.run_store.get_run(run_id)
    assert run.status == "queued"


# ---------------------------------------------------------- repo url / goal


def test_invalid_repo_url_is_422(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/runs",
        json={"repo_url": "not-a-url", "goal": "migrate it"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json() == {"error": {"code": "invalid_repo_url", "message": "repo_url is invalid"}}


def test_local_repo_path_refused_without_flag(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/runs",
        json={"repo_url": "/tmp/some/local/repo", "goal": "migrate it"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_repo_url"


def test_local_repo_path_allowed_with_flag(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setenv("PORTPILOT_ALLOW_LOCAL_REPOS", "1")
    resp = client.post(
        "/api/runs",
        json={"repo_url": "/tmp/some/local/repo", "goal": "migrate it"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("goal", ["", "hi", "x" * 2001])
def test_invalid_goal_is_422(client: TestClient, auth_headers: dict[str, str], goal: str) -> None:
    resp = client.post(
        "/api/runs",
        json={"repo_url": "https://github.com/octocat/hello-world", "goal": goal},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_goal"


def test_missing_field_is_422_with_contract_shape(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/api/runs", json={"goal": "migrate it"}, headers=auth_headers)
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body and "code" in body["error"] and "message" in body["error"]


# ------------------------------------------------------------------ rate limit


def test_rate_limited_after_ten_runs(client: TestClient, auth_headers: dict[str, str]) -> None:
    for _ in range(10):
        _create_run(client, auth_headers)
    resp = client.post(
        "/api/runs",
        json={"repo_url": "https://github.com/octocat/hello-world", "goal": "one too many"},
        headers=auth_headers,
    )
    assert resp.status_code == 429
    assert resp.json() == {
        "error": {"code": "rate_limited", "message": "too many runs created; try again later"}
    }


def test_rate_limit_is_per_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    for _ in range(10):
        _create_run(client, auth_headers)
    other_headers = {"Authorization": "Bearer test-token-123"}  # same token: still limited
    resp = client.post(
        "/api/runs",
        json={"repo_url": "https://github.com/octocat/hello-world", "goal": "still limited"},
        headers=other_headers,
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------- list


def test_list_runs_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/runs", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"runs": []}


def test_list_runs_summary_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get("/api/runs", headers=auth_headers)
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert len(runs) == 1
    summary = runs[0]
    assert summary["run_id"] == run_id
    assert set(summary.keys()) == {
        "run_id",
        "repo_url",
        "goal",
        "status",
        "created_at",
        "updated_at",
        "steps_total",
        "steps_done",
        "current_step_title",
        "usage",
    }
    assert summary["steps_total"] == 0
    assert summary["steps_done"] == 0
    assert summary["current_step_title"] is None


# ----------------------------------------------------------------------- get


def test_get_run_not_found_is_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/runs/run_missing", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_run_returns_run_plan_steps(client: TestClient, auth_headers: dict[str, str]) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get(f"/api/runs/{run_id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"run", "plan", "steps"}
    assert body["run"]["run_id"] == run_id
    assert body["plan"] is None
    assert body["steps"] == []


def test_get_step_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get(f"/api/runs/{run_id}/steps/step_missing", headers=auth_headers)
    assert resp.status_code == 404


def test_get_step_returns_step(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    from portpilot.core.models import ShortTermPlan

    run_id = _create_run(client, auth_headers)
    step = ShortTermPlan(
        step_id="step_1",
        run_id=run_id,
        seq=1,
        phase_id="phase_1",
        title="Do the thing",
        objective="obj",
    )
    deps.run_store.save_step(step)
    resp = client.get(f"/api/runs/{run_id}/steps/step_1", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["step"]["step_id"] == "step_1"


def test_get_step_wrong_run_is_404(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    from portpilot.core.models import ShortTermPlan

    run_id = _create_run(client, auth_headers)
    other_run_id = _create_run(client, auth_headers)
    step = ShortTermPlan(
        step_id="step_1", run_id=run_id, seq=1, phase_id="phase_1", title="t", objective="o"
    )
    deps.run_store.save_step(step)
    resp = client.get(f"/api/runs/{other_run_id}/steps/step_1", headers=auth_headers)
    assert resp.status_code == 404


# -------------------------------------------------------------------- events


def test_events_run_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/runs/run_missing/events", headers=auth_headers)
    assert resp.status_code == 404


def test_events_pagination_with_after_seq(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)  # emits seq=1 (run_created)
    deps.run_store.log_event(run_id, "note", payload={"n": 2})
    deps.run_store.log_event(run_id, "note", payload={"n": 3})

    resp = client.get(f"/api/runs/{run_id}/events", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]
    assert body["next_after_seq"] == 3

    resp2 = client.get(f"/api/runs/{run_id}/events?after_seq=1", headers=auth_headers)
    body2 = resp2.json()
    assert [e["seq"] for e in body2["events"]] == [2, 3]
    assert body2["next_after_seq"] == 3

    resp3 = client.get(f"/api/runs/{run_id}/events?after_seq=1&limit=1", headers=auth_headers)
    body3 = resp3.json()
    assert [e["seq"] for e in body3["events"]] == [2]
    assert body3["next_after_seq"] == 2


def test_events_no_new_events_next_after_seq_unchanged(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get(f"/api/runs/{run_id}/events?after_seq=99", headers=auth_headers)
    body = resp.json()
    assert body["events"] == []
    assert body["next_after_seq"] == 99


# ------------------------------------------------------------ pause / resume / cancel


def test_pause_queued_run_goes_straight_to_paused(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.post(f"/api/runs/{run_id}/pause", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "paused"}


def test_pause_running_run_sets_control(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    deps.run_store.update_run(run_id, status="running")
    resp = client.post(f"/api/runs/{run_id}/pause", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "running"}
    assert deps.run_store.get_run(run_id).control == "pause"


def test_pause_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post("/api/runs/run_missing/pause", headers=auth_headers)
    assert resp.status_code == 404


def test_resume_paused_run(client: TestClient, auth_headers: dict[str, str], deps: ApiDeps) -> None:
    run_id = _create_run(client, auth_headers)
    deps.run_store.update_run(run_id, status="paused", control="pause")
    resp = client.post(f"/api/runs/{run_id}/resume", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "queued"}
    run = deps.run_store.get_run(run_id)
    assert run.control is None


def test_resume_non_paused_run_is_409(client: TestClient, auth_headers: dict[str, str]) -> None:
    run_id = _create_run(client, auth_headers)  # status=queued
    resp = client.post(f"/api/runs/{run_id}/resume", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_resume_completed_run_is_409(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    deps.run_store.update_run(run_id, status="completed")
    resp = client.post(f"/api/runs/{run_id}/resume", headers=auth_headers)
    assert resp.status_code == 409


def test_cancel_queued_run_goes_straight_to_cancelled(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "cancelled"}


def test_cancel_paused_run_goes_straight_to_cancelled(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    deps.run_store.update_run(run_id, status="paused")
    resp = client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "cancelled"}


def test_cancel_running_run_sets_control(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    deps.run_store.update_run(run_id, status="running")
    resp = client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "running"}
    assert deps.run_store.get_run(run_id).control == "cancel"


def test_cancel_terminal_run_is_409(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    deps.run_store.update_run(run_id, status="failed")
    resp = client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers)
    assert resp.status_code == 409


def test_cancel_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post("/api/runs/run_missing/cancel", headers=auth_headers)
    assert resp.status_code == 404


# ------------------------------------------------------------------- artifacts


def test_list_artifacts_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get(f"/api/runs/{run_id}/artifacts", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"artifacts": []}


def test_get_artifact_roundtrip(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    artifact_id = deps.run_store.put_artifact(run_id, None, "survey", {"languages": {"python": 3}})

    list_resp = client.get(f"/api/runs/{run_id}/artifacts", headers=auth_headers)
    assert list_resp.status_code == 200
    metas = list_resp.json()["artifacts"]
    assert len(metas) == 1
    assert metas[0]["artifact_id"] == artifact_id
    assert "content" not in metas[0]

    get_resp = client.get(f"/api/runs/{run_id}/artifacts/{artifact_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    artifact = get_resp.json()["artifact"]
    assert artifact["artifact_id"] == artifact_id
    assert artifact["content"] == {"languages": {"python": 3}}


def test_get_artifact_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get(f"/api/runs/{run_id}/artifacts/art_missing", headers=auth_headers)
    assert resp.status_code == 404


def test_get_artifact_wrong_run_is_404(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    run_id = _create_run(client, auth_headers)
    other_run_id = _create_run(client, auth_headers)
    artifact_id = deps.run_store.put_artifact(run_id, None, "survey", {"x": 1})
    resp = client.get(f"/api/runs/{other_run_id}/artifacts/{artifact_id}", headers=auth_headers)
    assert resp.status_code == 404


# -------------------------------------------------------------------- download


def test_download_with_sandbox(
    client: TestClient, auth_headers: dict[str, str], sandbox: Any
) -> None:
    run_id = _create_run(client, auth_headers)
    resp = client.get(f"/api/runs/{run_id}/download", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert resp.content == sandbox.archive
    assert sandbox.export_calls == [run_id]


def test_download_without_sandbox_is_503(deps: ApiDeps, auth_headers: dict[str, str]) -> None:
    from portpilot.api.app import create_app

    deps.sandbox = None
    app = create_app(deps)
    with TestClient(app) as no_sandbox_client:
        run_id = _create_run(no_sandbox_client, auth_headers)
        resp = no_sandbox_client.get(f"/api/runs/{run_id}/download", headers=auth_headers)
        assert resp.status_code == 503


def test_download_run_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/runs/run_missing/download", headers=auth_headers)
    assert resp.status_code == 404


# ------------------------------------------------------------------------ tools


def test_list_tools_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/tools", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"tools": []}


def test_list_tools_and_get_tool(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    from portpilot.core.models import ToolRecord

    record = ToolRecord(
        name="grep_repo",
        version=1,
        description="grep the repo",
        when_to_use="when searching",
        input_schema={},
        output_schema={},
        files={"main.py": "def run(params): return {}"},
        status="active",
    )
    deps.tool_store.save(record)

    list_resp = client.get("/api/tools", headers=auth_headers)
    assert list_resp.status_code == 200
    tools = list_resp.json()["tools"]
    assert len(tools) == 1
    summary = tools[0]
    assert summary["name"] == "grep_repo"
    assert summary["versions_count"] == 1
    assert "files" not in summary and "tests" not in summary

    get_resp = client.get("/api/tools/grep_repo", headers=auth_headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["name"] == "grep_repo"
    assert len(body["versions"]) == 1
    assert body["versions"][0]["files"] == {"main.py": "def run(params): return {}"}


def test_get_tool_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/tools/missing_tool", headers=auth_headers)
    assert resp.status_code == 404


def test_list_tools_filter_by_status(
    client: TestClient, auth_headers: dict[str, str], deps: ApiDeps
) -> None:
    from portpilot.core.models import ToolRecord

    deps.tool_store.save(
        ToolRecord(
            name="a",
            version=1,
            description="d",
            when_to_use="w",
            input_schema={},
            output_schema={},
            files={},
            status="draft",
        )
    )
    resp = client.get("/api/tools?status=active", headers=auth_headers)
    assert resp.json() == {"tools": []}


# -------------------------------------------------------------------- knowledge


def test_search_knowledge(client: TestClient, auth_headers: dict[str, str], deps: ApiDeps) -> None:
    from portpilot.core.models import KnowledgeItem

    deps.knowledge.upsert(
        KnowledgeItem(id="k1", kind="lesson", title="Use uv", body="uv run pytest is fast")
    )
    resp = client.get("/api/knowledge/search?q=uv", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "hits" in body
    if body["hits"]:
        hit = body["hits"][0]
        assert set(hit.keys()) == {"item", "score", "via"}


def test_list_knowledge(client: TestClient, auth_headers: dict[str, str], deps: ApiDeps) -> None:
    from portpilot.core.models import KnowledgeItem

    deps.knowledge.upsert(KnowledgeItem(id="k1", kind="gotcha", title="Gotcha", body="body text"))
    resp = client.get("/api/knowledge?kinds=gotcha", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "k1"
