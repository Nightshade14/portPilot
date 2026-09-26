"""Shared store contract suite (plan section 4.4). Owner: Lane B.

One suite, parametrized over a `store` fixture:
- `memory` always runs.
- `atlas` runs only when MONGODB_URI is set; otherwise it is skipped
  (marked `atlas`). It uses a unique throwaway db per session, dropped at
  teardown.

`reopen` returns a store backed by the same underlying data: the same
InMemoryStore instance, or a fresh AtlasStore on the same db. It is how the
resume test proves persistence survives a new process/connection.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from portpilot.models import Policy
from portpilot.store.base import NotFound, StoreError
from portpilot.store.memory import InMemoryStore

RUN_ID_RE = re.compile(r"^run_[0-9a-f]{12}$")
ART_ID_RE = re.compile(r"^art_[0-9a-f]{12}$")

# A store backed by durable state, plus a callable that reopens fresh over it.
StoreBundle = tuple[Any, Callable[[], Any]]


@pytest.fixture(params=["memory", "atlas"])
def store_bundle(request: pytest.FixtureRequest):
    if request.param == "memory":
        store = InMemoryStore()
        yield store, (lambda: store)
        return

    # atlas
    request.applymarker(pytest.mark.atlas)
    uri = os.getenv("MONGODB_URI")
    if not uri:
        pytest.skip("MONGODB_URI not set; skipping live Atlas store tests")

    from pymongo import MongoClient

    from portpilot.store.atlas import AtlasStore

    db_name = f"portpilot_test_{uuid.uuid4().hex[:12]}"
    store = AtlasStore(uri, db_name)

    def _reopen() -> AtlasStore:
        return AtlasStore(uri, db_name)

    try:
        yield store, _reopen
    finally:
        client: MongoClient = MongoClient(uri, serverSelectionTimeoutMS=8000)
        try:
            client.drop_database(db_name)
        finally:
            client.close()


@pytest.fixture
def store(store_bundle: StoreBundle) -> Any:
    return store_bundle[0]


# --- runs ---------------------------------------------------------------
def test_create_run_returns_running_run_with_expected_shape(store: Any) -> None:
    run_id = store.create_run("/src/app.py", policy_version=1)
    assert RUN_ID_RE.match(run_id)
    run = store.get_run(run_id)
    assert run["run_id"] == run_id
    assert run["source_path"] == "/src/app.py"
    assert run["policy_version"] == 1
    assert run["status"] == "running"
    assert run["current_milestone"] is None
    assert run["attempt"] == 0
    for key in ("created_at", "updated_at"):
        assert isinstance(run[key], datetime)
        assert run[key].tzinfo is not None


def test_get_run_unknown_id_raises_not_found(store: Any) -> None:
    with pytest.raises(NotFound):
        store.get_run("run_000000000000")


def test_update_run_sets_fields_and_bumps_updated_at(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    before = store.get_run(run_id)
    store.update_run(run_id, status="paused", attempt=2, current_milestone="generation")
    after = store.get_run(run_id)
    assert after["status"] == "paused"
    assert after["attempt"] == 2
    assert after["current_milestone"] == "generation"
    assert after["updated_at"] >= before["updated_at"]


def test_update_run_unknown_id_raises_not_found(store: Any) -> None:
    with pytest.raises(NotFound):
        store.update_run("run_000000000000", status="failed")


def test_memory_run_docs_are_deep_copies() -> None:
    store = InMemoryStore()
    run_id = store.create_run("/src/app.py", 1)
    doc = store.get_run(run_id)
    doc["status"] = "tampered"
    assert store.get_run(run_id)["status"] == "running"


# --- milestones ---------------------------------------------------------
def test_start_milestone_sets_current_milestone(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    store.start_milestone(run_id, "source_analysis", 0)
    assert store.get_run(run_id)["current_milestone"] == "source_analysis"


def test_completed_milestones_in_completion_order(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    store.start_milestone(run_id, "source_analysis", 0)
    store.start_milestone(run_id, "generation", 0)
    store.complete_milestone(run_id, "generation", 0, [])
    store.complete_milestone(run_id, "source_analysis", 0, [])
    assert store.completed_milestones(run_id) == [
        ("generation", 0),
        ("source_analysis", 0),
    ]


def test_completed_milestones_empty_for_unstarted_run(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    assert store.completed_milestones(run_id) == []


# --- artifacts ----------------------------------------------------------
def test_put_and_get_artifact_roundtrip(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    art_id = store.put_artifact(run_id, "source_analysis", 0, {"k": "v"})
    assert ART_ID_RE.match(art_id)
    art = store.get_artifact(art_id)
    assert art["artifact_id"] == art_id
    assert art["run_id"] == run_id
    assert art["kind"] == "source_analysis"
    assert art["attempt"] == 0
    assert art["content"] == {"k": "v"}
    assert isinstance(art["created_at"], datetime)
    assert art["created_at"].tzinfo is not None


def test_get_artifact_unknown_id_raises_not_found(store: Any) -> None:
    with pytest.raises(NotFound):
        store.get_artifact("art_000000000000")


def test_latest_artifact_returns_newest_or_none(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    assert store.latest_artifact(run_id, "test_output") is None
    store.put_artifact(run_id, "test_output", 0, {"n": 1})
    second = store.put_artifact(run_id, "test_output", 1, {"n": 2})
    latest = store.latest_artifact(run_id, "test_output")
    assert latest is not None
    assert latest["artifact_id"] == second
    assert latest["content"] == {"n": 2}


def test_artifacts_filter_and_ascending_order(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    a0 = store.put_artifact(run_id, "test_output", 0, {"n": 0})
    b0 = store.put_artifact(run_id, "diagnosis", 0, {"n": 1})
    a1 = store.put_artifact(run_id, "test_output", 1, {"n": 2})
    all_ids = [a["artifact_id"] for a in store.artifacts(run_id)]
    assert all_ids == [a0, b0, a1]
    test_ids = [a["artifact_id"] for a in store.artifacts(run_id, kind="test_output")]
    assert test_ids == [a0, a1]
    attempt1 = [a["artifact_id"] for a in store.artifacts(run_id, attempt=1)]
    assert attempt1 == [a1]


def test_memory_artifact_content_is_deep_copied() -> None:
    store = InMemoryStore()
    run_id = store.create_run("/src/app.py", 1)
    payload = {"nested": {"x": 1}}
    art_id = store.put_artifact(run_id, "source_analysis", 0, payload)
    payload["nested"]["x"] = 999
    assert store.get_artifact(art_id)["content"] == {"nested": {"x": 1}}


# --- policies -----------------------------------------------------------
def _policy(version: int, status: str = "candidate") -> Policy:
    return Policy(
        name="flask-to-hono",
        version=version,
        status=status,  # type: ignore[arg-type]
        body=f"body v{version}",
        rules=[f"rule-{version}"],
    )


def test_save_and_get_policy_by_version(store: Any) -> None:
    store.save_policy(_policy(1, "active"))
    got = store.get_policy("flask-to-hono", 1)
    assert isinstance(got, Policy)
    assert got.version == 1
    assert got.status == "active"


def test_save_duplicate_policy_raises_store_error(store: Any) -> None:
    store.save_policy(_policy(1, "active"))
    with pytest.raises(StoreError):
        store.save_policy(_policy(1, "candidate"))


def test_get_policy_without_version_returns_active(store: Any) -> None:
    store.save_policy(_policy(1, "retired"))
    store.save_policy(_policy(2, "active"))
    store.save_policy(_policy(3, "candidate"))
    active = store.get_policy("flask-to-hono")
    assert active.version == 2
    assert active.status == "active"


def test_get_policy_active_missing_raises_not_found(store: Any) -> None:
    store.save_policy(_policy(1, "candidate"))
    with pytest.raises(NotFound):
        store.get_policy("flask-to-hono")


def test_get_policy_unknown_version_raises_not_found(store: Any) -> None:
    with pytest.raises(NotFound):
        store.get_policy("flask-to-hono", 99)


def test_list_policies_sorted_ascending_by_version(store: Any) -> None:
    store.save_policy(_policy(3))
    store.save_policy(_policy(1))
    store.save_policy(_policy(2))
    assert [p.version for p in store.list_policies("flask-to-hono")] == [1, 2, 3]


def test_set_policy_status_updates_status_and_decision(store: Any) -> None:
    store.save_policy(_policy(1, "candidate"))
    store.set_policy_status("flask-to-hono", 1, "active", {"promoted": True})
    got = store.get_policy("flask-to-hono", 1)
    assert got.status == "active"
    assert got.decision == {"promoted": True}


def test_set_policy_status_unknown_raises_not_found(store: Any) -> None:
    with pytest.raises(NotFound):
        store.set_policy_status("flask-to-hono", 42, "active", {})


# --- events -------------------------------------------------------------
def test_events_sorted_and_seq_monotonic(store: Any) -> None:
    run_id = store.create_run("/src/app.py", 1)
    store.log_event(run_id, "tool_call", "generation", {"i": 0})
    store.log_event(run_id, "tool_result", "generation", {"i": 1})
    store.log_event(run_id, "checkpoint", "generation", {"i": 2})
    events = store.events(run_id)
    assert [e["payload"]["i"] for e in events] == [0, 1, 2]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    first = events[0]
    assert first["run_id"] == run_id
    assert first["type"] == "tool_call"
    assert first["milestone"] == "generation"
    assert isinstance(first["ts"], datetime) and first["ts"].tzinfo is not None


# --- resume -------------------------------------------------------------
def test_resume_recovers_milestones_artifacts_and_active_policy(
    store_bundle: StoreBundle,
) -> None:
    store, reopen = store_bundle
    run_id = store.create_run("/src/app.py", 1)
    store.save_policy(_policy(1, "active"))

    store.start_milestone(run_id, "source_analysis", 0)
    a1 = store.put_artifact(run_id, "source_analysis", 0, {"routes": 3})
    store.complete_milestone(run_id, "source_analysis", 0, [a1])

    store.start_milestone(run_id, "generation", 0)
    a2 = store.put_artifact(run_id, "target_version", 0, {"files": 5})
    store.complete_milestone(run_id, "generation", 0, [a2])

    fresh = reopen()
    assert fresh.completed_milestones(run_id) == [
        ("source_analysis", 0),
        ("generation", 0),
    ]
    assert {a["artifact_id"] for a in fresh.artifacts(run_id)} == {a1, a2}
    assert fresh.get_artifact(a1)["content"] == {"routes": 3}
    assert fresh.get_policy("flask-to-hono").version == 1
