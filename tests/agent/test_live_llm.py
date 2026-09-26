"""One `llm`-marked live test (lane-a.md tests section): a tiny local repo, goal
"add a function slugify with tests", asserting the run completes and the checks pass.
Uses `LocalSandboxManager` and in-memory stores; real Anthropic/OpenRouter model calls.

Skipped by default (no OPENROUTER_API_KEY): a plain `uv run pytest` must stay offline
per lane-a.md's Done criteria. Run explicitly with:
  uv run pytest tests/agent/test_live_llm.py -m llm -q -s
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import make_settings
from dotenv import dotenv_values

from portpilot.agent.deps import AgentDeps, default_model_factory
from portpilot.agent.loop import run_migration
from portpilot.core.fakes import (
    FakeEmbedder,
    InMemoryKnowledgeStore,
    InMemoryRunStore,
    InMemoryToolStore,
    LocalSandboxManager,
)
from portpilot.core.models import Budgets, Run, new_id

ENV_PATH = "/Users/satyamchatrola/codes/personal/portPilot/.env"


def _load_env() -> dict[str, str]:
    values = dotenv_values(ENV_PATH)
    return {k: v for k, v in values.items() if v}


_env = _load_env()
pytestmark = pytest.mark.llm

requires_live_llm = pytest.mark.skipif(
    not _env.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set in .env -- live LLM test skipped by default",
)


class _NullCliInstaller:
    def check_environment(self, run_id: str) -> dict:
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

        return InstallResult(name=name, ok=False, refused=True, reason="not on the allow-list")

    def allowlist(self) -> dict:
        return {}


def _make_tiny_python_repo(root: Path) -> Path:
    repo = root / "tiny_repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "tinyrepo"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        'dependencies = []\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    (repo / "src").mkdir()
    (repo / "src" / "tinyrepo").mkdir()
    (repo / "src" / "tinyrepo" / "__init__.py").write_text("")
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "portpilot@localhost"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "PortPilot"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)
    return repo


@requires_live_llm
def test_live_add_slugify_function_with_tests():
    """Live cost: this makes real OpenRouter calls (planner, executor loop, selector,
    reflection, digest). Run once and report tokens used -- see the printed
    `run.usage` in the test output (requires `-s`)."""

    runs_root = Path(__file__).resolve().parents[2] / "runs" / "_pytest"
    runs_root.mkdir(parents=True, exist_ok=True)
    sandbox_root = runs_root / f"live-{new_id('sbx')}"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    repo_path = _make_tiny_python_repo(sandbox_root / "src_repo")

    settings = make_settings(
        openrouter_api_key=_env["OPENROUTER_API_KEY"],
        openrouter_base_url=_env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model_id=_env.get("MODEL_ID", "anthropic/claude-sonnet-4.5"),
        model_id_aux=_env.get("MODEL_ID_AUX", "google/gemini-2.5-flash-lite"),
    )

    deps = AgentDeps(
        run_store=InMemoryRunStore(),
        tool_store=InMemoryToolStore(),
        knowledge=InMemoryKnowledgeStore(FakeEmbedder()),
        sandbox=LocalSandboxManager(root=sandbox_root / "sandbox"),
        installer=_NullCliInstaller(),
        tool_library=None,
        settings=settings,
        model_factory=default_model_factory(settings),
    )

    run = Run(
        run_id=new_id("run"),
        repo_url=str(repo_path),
        goal=(
            "Add a function slugify(text: str) -> str that converts a string into a "
            "URL-safe slug (lowercase, spaces/underscores to hyphens, strip other "
            "punctuation), with pytest tests covering at least: basic conversion, "
            "already-slugified input, and punctuation removal."
        ),
        budgets=Budgets(
            max_steps=6,
            max_tokens=3_000_000,
            max_minutes=30,
            max_tools_created=2,
            max_selected_tools=8,
            max_mid_step_loads=3,
        ),
    )
    deps.run_store.create_run(run)

    result = run_migration(deps, run.run_id, "live-test-worker")

    print(f"\n[live llm test] final status: {result.status}")
    print(f"[live llm test] usage: {result.usage.to_doc()}")

    assert result.status == "completed", (
        f"run did not complete (status={result.status}, error={result.error}); "
        f"usage so far: {result.usage.to_doc()}"
    )

    steps = deps.run_store.steps(run.run_id)
    assert steps, "expected at least one step to have run"
    assert all(s.status == "done" for s in steps), [(s.title, s.status, s.outcome) for s in steps]

    verify_events = [e for e in deps.run_store.events(run.run_id) if e["type"] == "step_verified"]
    assert verify_events, "expected at least one step_verified event"
    assert all(e["payload"]["ok"] for e in verify_events), verify_events
