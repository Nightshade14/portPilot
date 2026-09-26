"""Shared fixtures for tests/api: a FastAPI TestClient wired to the in-memory fakes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from portpilot.api.app import ApiDeps, create_app
from portpilot.core.config import MvpSettings
from portpilot.core.fakes import (
    FakeEmbedder,
    InMemoryKnowledgeStore,
    InMemoryRunStore,
    InMemoryToolStore,
)

API_TOKEN = "test-token-123"


def make_settings(**overrides: Any) -> MvpSettings:
    base = {
        "mongodb_uri": None,
        "mongodb_db": "portpilot_mvp_test",
        "openrouter_api_key": None,
        "openrouter_base_url": "https://openrouter.ai/api/v1",
        "model_id": "anthropic/claude-sonnet-4.5",
        "model_id_aux": "google/gemini-2.5-flash-lite",
        "model_temperature": 0.1,
        "voyage_api_key": None,
        "voyage_base_url": "https://api.voyageai.com/v1",
        "embedding_model": "voyage-4",
        "embedding_dims": 64,
        "api_token": API_TOKEN,
        "api_cors_origins": ("https://example.vercel.app",),
        "sandbox_image": "portpilot-sandbox:dev",
        "buildkit_addr": None,
        "worker_id": "test-worker",
        "lease_seconds": 60,
        "store_backend": "memory",
    }
    base.update(overrides)
    return MvpSettings(**base)


class FakeSandbox:
    """Minimal SandboxManager stub: only export_archive is exercised by the API."""

    def __init__(self, archive: bytes = b"fake-archive-bytes") -> None:
        self.archive = archive
        self.export_calls: list[str] = []

    def ensure(self, run_id: str, repo_url: str | None = None) -> str:
        return f"fake-{run_id}"

    def exec(self, run_id: str, command: str, **kwargs: Any):
        raise NotImplementedError

    def write_file(self, run_id: str, path: str, content: str) -> None:
        raise NotImplementedError

    def read_file(self, run_id: str, path: str) -> str:
        raise NotImplementedError

    def sandbox(self, run_id: str) -> Any:
        raise NotImplementedError

    def commit(self, run_id: str, message: str) -> str:
        raise NotImplementedError

    def restore(self, run_id: str, sha: str) -> None:
        raise NotImplementedError

    def export_archive(self, run_id: str) -> bytes:
        self.export_calls.append(run_id)
        return self.archive

    def stop(self, run_id: str) -> None:
        raise NotImplementedError

    def destroy(self, run_id: str) -> None:
        raise NotImplementedError


@pytest.fixture
def settings() -> MvpSettings:
    return make_settings()


@pytest.fixture
def sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def deps(settings: MvpSettings, sandbox: FakeSandbox) -> ApiDeps:
    return ApiDeps(
        run_store=InMemoryRunStore(),
        tool_store=InMemoryToolStore(),
        knowledge=InMemoryKnowledgeStore(FakeEmbedder(dims=settings.embedding_dims)),
        sandbox=sandbox,
        settings=settings,
    )


@pytest.fixture
def client(deps: ApiDeps) -> TestClient:
    app = create_app(deps)
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}
