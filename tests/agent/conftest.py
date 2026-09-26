"""Shared fixtures for `tests/agent/` (offline: fakes only, no network)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest

from portpilot.agent.deps import AgentDeps
from portpilot.core.config import MvpSettings
from portpilot.core.fakes import (
    FakeEmbedder,
    InMemoryKnowledgeStore,
    InMemoryRunStore,
    InMemoryToolStore,
    LocalSandboxManager,
)
from portpilot.core.models import Budgets, Run, new_id

# `$TMPDIR` isn't usable by git in this sandbox (per lane-a.md tests section); use a
# temp git repo under runs/_pytest/ instead, same as the frozen fakes doc.
PYTEST_RUNS_ROOT = Path(__file__).resolve().parents[2] / "runs" / "_pytest"


def make_settings(**overrides: Any) -> MvpSettings:
    defaults: dict[str, Any] = {
        "mongodb_uri": None,
        "mongodb_db": "portpilot_test",
        "openrouter_api_key": None,
        "openrouter_base_url": "https://openrouter.ai/api/v1",
        "model_id": "anthropic/claude-sonnet-4.5",
        "model_id_aux": "google/gemini-2.5-flash-lite",
        "model_temperature": 0.1,
        "voyage_api_key": None,
        "voyage_base_url": "https://api.voyageai.com/v1",
        "embedding_model": "voyage-4",
        "embedding_dims": 1024,
        "api_token": None,
        "api_cors_origins": (),
        "sandbox_image": "portpilot-sandbox:dev",
        "buildkit_addr": None,
        "worker_id": "test-worker",
        "lease_seconds": 60,
        "store_backend": "memory",
    }
    defaults.update(overrides)
    return MvpSettings(**defaults)


@pytest.fixture
def sandbox_root(tmp_path_factory: pytest.TempPathFactory):
    PYTEST_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    root = PYTEST_RUNS_ROOT / f"sbx-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def stores():
    return {
        "run_store": InMemoryRunStore(),
        "tool_store": InMemoryToolStore(),
        "knowledge": InMemoryKnowledgeStore(FakeEmbedder()),
    }


def make_deps(
    *,
    sandbox_root: Path,
    run_store=None,
    tool_store=None,
    knowledge=None,
    tool_library=None,
    model_factory=None,
    session_manager_factory=None,
    offload_storage=None,
    render_markdown=None,
    author_tool=None,
    shell_guard=None,
    settings: MvpSettings | None = None,
) -> AgentDeps:
    from fakes import ScriptedModel

    settings = settings or make_settings()
    return AgentDeps(
        run_store=run_store or InMemoryRunStore(),
        tool_store=tool_store or InMemoryToolStore(),
        knowledge=knowledge or InMemoryKnowledgeStore(FakeEmbedder()),
        sandbox=LocalSandboxManager(root=sandbox_root),
        installer=_NullCliInstaller(),
        tool_library=tool_library,
        settings=settings,
        model_factory=model_factory or (lambda role: ScriptedModel()),
        session_manager_factory=session_manager_factory,
        offload_storage=offload_storage,
        render_markdown=render_markdown,
        author_tool=author_tool,
        shell_guard=shell_guard,
    )


class _NullCliInstaller:
    """Minimal `CliInstaller`: nothing is installed, nothing is allow-listed."""

    def check_environment(self, run_id: str) -> dict[str, Any]:
        return {
            "os": "linux",
            "arch": "x86_64",
            "disk_free_mb": 10_000,
            "mem_mb": 4_000,
            "installed": {},
            "allowlisted": [],
            "repo_languages": {},
        }

    def install(self, run_id: str, name: str):
        from portpilot.core.models import InstallResult

        return InstallResult(
            name=name, ok=False, refused=True, reason=f"{name!r} is not on the allow-list"
        )

    def allowlist(self) -> dict[str, dict[str, Any]]:
        return {}


def make_run(**overrides: Any) -> Run:
    defaults: dict[str, Any] = {
        "run_id": new_id("run"),
        "repo_url": "",
        "goal": "Add a function slugify with tests",
        "budgets": Budgets(
            max_steps=10,
            max_tokens=10_000_000,
            max_minutes=240,
            max_tools_created=5,
            max_selected_tools=8,
            max_mid_step_loads=3,
        ),
    }
    defaults.update(overrides)
    return Run(**defaults)


__all__ = ["PYTEST_RUNS_ROOT", "make_deps", "make_run", "make_settings"]
