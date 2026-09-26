"""CLI tests: typer.testing.CliRunner with a monkeypatched get_store returning
a FakeStore loaded from the demo fixtures, and monkeypatched orchestrator
functions. Covers an invalid --pause-after, NotFound, and the not-implemented
path."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from portpilot import cli
from portpilot.harness import orchestrator
from portpilot.store.base import NotFound

runner = CliRunner()


@pytest.fixture
def completed_store(monkeypatch, make_fake_store):
    store = make_fake_store("completed_run")
    monkeypatch.setattr(cli, "get_store", lambda: store)
    return store


@pytest.fixture
def paused_store(monkeypatch, make_fake_store):
    store = make_fake_store("paused_run")
    monkeypatch.setattr(cli, "get_store", lambda: store)
    return store


# --- status / events / policies (pure store reads) --------------------------


def test_status_renders_completed_run(completed_store):
    result = runner.invoke(cli.app, ["status", "run_a1b2c3d4e5f6"])
    assert result.exit_code == 0
    assert "run_a1b2c3d4e5f6" in result.output
    assert "completed" in result.output
    assert "10/10" in result.output


def test_status_unknown_run_is_clean_error_exit_1(completed_store):
    result = runner.invoke(cli.app, ["status", "run_does_not_exist"])
    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Traceback" not in result.output


def test_events_renders_timeline(completed_store):
    result = runner.invoke(cli.app, ["events", "run_a1b2c3d4e5f6"])
    assert result.exit_code == 0
    assert "checkpoint" in result.output


def test_events_unknown_run_exit_1(completed_store):
    result = runner.invoke(cli.app, ["events", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_policies_lists_versions_without_run(completed_store):
    result = runner.invoke(cli.app, ["policies"])
    assert result.exit_code == 0
    assert "v1" in result.output and "v2" in result.output
    assert "retired" in result.output and "active" in result.output


def test_policies_with_run_shows_comparison_and_decision(completed_store):
    result = runner.invoke(cli.app, ["policies", "--run", "run_a1b2c3d4e5f6"])
    assert result.exit_code == 0
    assert "fixed" in result.output
    assert "PROMOTED" in result.output


# --- run / resume with a monkeypatched orchestrator -------------------------


def test_run_prints_run_id_and_status(completed_store, monkeypatch):
    monkeypatch.setattr(orchestrator, "start_run", lambda store, **kw: "run_a1b2c3d4e5f6")
    result = runner.invoke(cli.app, ["run", "--policy", "v1"])
    assert result.exit_code == 0
    assert "run started" in result.output
    assert "run_a1b2c3d4e5f6" in result.output


def test_run_paused_prints_resume_hint(paused_store, monkeypatch):
    monkeypatch.setattr(orchestrator, "start_run", lambda store, **kw: "run_9f8e7d6c5b4a")
    result = runner.invoke(cli.app, ["run", "--policy", "v1", "--pause-after", "candidate_policy"])
    assert result.exit_code == 0
    assert "resume with" in result.output
    assert "portpilot resume run_9f8e7d6c5b4a" in result.output


def test_run_invalid_pause_after_exit_2(completed_store):
    result = runner.invoke(cli.app, ["run", "--pause-after", "banana"])
    assert result.exit_code == 2
    assert "invalid --pause-after" in result.output
    assert "Traceback" not in result.output


def test_run_invalid_policy_exit_2(completed_store):
    result = runner.invoke(cli.app, ["run", "--policy", "vX"])
    assert result.exit_code == 2
    assert "invalid --policy" in result.output


def test_run_not_implemented_orchestrator_exit_2(completed_store, monkeypatch):
    def _boom(*a, **k):
        raise NotImplementedError("Lane C: start_run")

    monkeypatch.setattr(orchestrator, "start_run", _boom)
    result = runner.invoke(cli.app, ["run"])
    assert result.exit_code == 2
    assert "not implemented yet" in result.output
    assert "lane C" in result.output
    assert "Traceback" not in result.output


def test_resume_renders_status(completed_store, monkeypatch):
    monkeypatch.setattr(orchestrator, "resume", lambda store, run_id, **kw: run_id)
    result = runner.invoke(cli.app, ["resume", "run_a1b2c3d4e5f6"])
    assert result.exit_code == 0
    assert "completed" in result.output


def test_resume_not_implemented_exit_2(completed_store, monkeypatch):
    def _boom(*a, **k):
        raise NotImplementedError("Lane C: resume")

    monkeypatch.setattr(orchestrator, "resume", _boom)
    result = runner.invoke(cli.app, ["resume", "run_a1b2c3d4e5f6"])
    assert result.exit_code == 2
    assert "not implemented yet" in result.output


def test_resume_not_found_exit_1(completed_store, monkeypatch):
    def _missing(*a, **k):
        raise NotFound("gone")

    monkeypatch.setattr(orchestrator, "resume", _missing)
    result = runner.invoke(cli.app, ["resume", "gone"])
    assert result.exit_code == 1
    assert "not found" in result.output


# --- contracts / seed delegate to Lanes A and B ------------------------------


def test_contracts_exits_with_contracts_command_return_code(monkeypatch):
    import portpilot.contracts.cli as contracts_cli

    calls = []

    def _fake(source_only, target):
        calls.append((source_only, target))
        return 1

    monkeypatch.setattr(contracts_cli, "contracts_command", _fake)
    result = runner.invoke(cli.app, ["contracts", "--target", "some/dir"])
    assert result.exit_code == 1
    assert calls == [(False, "some/dir")]


def test_seed_installs_v1_as_active_policy(monkeypatch):
    from portpilot.config import POLICY_NAME
    from portpilot.store.memory import InMemoryStore

    store = InMemoryStore()
    monkeypatch.setattr(cli, "get_store", lambda: store)
    result = runner.invoke(cli.app, ["seed"])
    assert result.exit_code == 0, result.output
    assert "seeded" in result.output
    assert store.get_policy(POLICY_NAME).version == 1


def test_help_lists_all_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("run", "resume", "status", "events", "policies", "contracts", "seed", "smoke"):
        assert cmd in result.output
