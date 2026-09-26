"""Startup auth guard: refuse with no api_token unless PORTPILOT_API_INSECURE_DEV=1."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portpilot.api.app import ApiDeps, create_app
from portpilot.core.config import MvpSettings
from portpilot.core.fakes import InMemoryKnowledgeStore, InMemoryRunStore, InMemoryToolStore


def _settings_without_token() -> MvpSettings:
    return MvpSettings(
        mongodb_uri=None,
        mongodb_db="portpilot_mvp_test",
        openrouter_api_key=None,
        openrouter_base_url="https://openrouter.ai/api/v1",
        model_id="anthropic/claude-sonnet-4.5",
        model_id_aux="google/gemini-2.5-flash-lite",
        model_temperature=0.1,
        voyage_api_key=None,
        voyage_base_url="https://api.voyageai.com/v1",
        embedding_model="voyage-4",
        embedding_dims=64,
        api_token=None,
        api_cors_origins=(),
        sandbox_image="portpilot-sandbox:dev",
        buildkit_addr=None,
        worker_id="test-worker",
        lease_seconds=60,
        store_backend="memory",
    )


def _deps_without_token() -> ApiDeps:
    return ApiDeps(
        run_store=InMemoryRunStore(),
        tool_store=InMemoryToolStore(),
        knowledge=InMemoryKnowledgeStore(),
        sandbox=None,
        settings=_settings_without_token(),
    )


def test_refuses_to_start_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORTPILOT_API_INSECURE_DEV", raising=False)
    with pytest.raises(RuntimeError, match="api_token is unset"):
        create_app(_deps_without_token())


def test_starts_insecure_with_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTPILOT_API_INSECURE_DEV", "1")
    app = create_app(_deps_without_token())
    client = TestClient(app)
    # No Authorization header at all -- insecure dev mode allows every request.
    resp = client.get("/api/runs")
    assert resp.status_code == 200
