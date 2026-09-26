"""Tests for the persist_checkpoint tool. Owner: Lane B."""

from __future__ import annotations

from portpilot.harness.context import bind
from portpilot.harness.tools.persist_checkpoint import persist_checkpoint
from portpilot.store.memory import InMemoryStore


def test_persist_checkpoint_logs_event_and_updates_run() -> None:
    store = InMemoryStore()
    bind(store)
    run_id = store.create_run("/src/app.py", 1)

    result = persist_checkpoint(run_id=run_id, milestone="generation", note="halfway")

    assert result == "ok"

    events = store.events(run_id)
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "checkpoint"
    assert event["milestone"] == "generation"
    assert event["payload"] == {"note": "halfway"}

    checkpoint = store.get_run(run_id)["last_checkpoint"]
    assert checkpoint["milestone"] == "generation"
    assert checkpoint["note"] == "halfway"
    assert "ts" in checkpoint
