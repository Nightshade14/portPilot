"""Contract tests for RunStore, parametrized over InMemoryRunStore and AtlasRunStore.

Behavior here is the shared contract both implementations must satisfy (core.fakes is
the reference; MVP_PLAN 3.7/4 and core.interfaces.RunStore are the spec). The Atlas
case uses marker `mongo`, skipped when PORTPILOT_TEST_MONGODB_URI is unset. Each Atlas
test gets a unique db (`pp_test_m_<hex>`) dropped in a finalizer.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest

from portpilot.core.fakes import InMemoryRunStore
from portpilot.core.interfaces import Conflict, NotFound, RunStore
from portpilot.core.models import LongTermPlan, Phase, Run, ShortTermPlan, new_id


def _make_run(**overrides) -> Run:
    defaults: dict = {
        "run_id": new_id("run"),
        "repo_url": "https://example.invalid/repo.git",
        "goal": "migrate flask to hono",
    }
    defaults.update(overrides)
    return Run(**defaults)


def _make_plan(run_id: str, version: int = 1) -> LongTermPlan:
    return LongTermPlan(
        run_id=run_id,
        version=version,
        goal="migrate",
        phases=[Phase(id="p1", title="Phase 1", goal="do the thing")],
    )


def _make_step(run_id: str, seq: int, **overrides) -> ShortTermPlan:
    defaults: dict = {
        "step_id": new_id("step"),
        "run_id": run_id,
        "seq": seq,
        "phase_id": "p1",
        "title": f"step {seq}",
        "objective": "do it",
    }
    defaults.update(overrides)
    return ShortTermPlan(**defaults)


@pytest.fixture(params=["memory", pytest.param("atlas", marks=pytest.mark.mongo)])
def run_store(request) -> Iterator[RunStore]:
    if request.param == "memory":
        store = InMemoryRunStore()
        yield store
        return

    uri = request.getfixturevalue("mongo_uri")
    db_name = request.getfixturevalue("mongo_db_name")
    from portpilot.store.v2.atlas import AtlasRunStore

    store = AtlasRunStore(uri, db_name)
    try:
        yield store
    finally:
        store.drop()
        store.close()


def test_create_and_get_run(run_store: RunStore) -> None:
    run = _make_run()
    run_id = run_store.create_run(run)
    assert run_id == run.run_id

    fetched = run_store.get_run(run_id)
    assert fetched.run_id == run.run_id
    assert fetched.goal == run.goal
    assert fetched.status == "queued"


def test_create_run_duplicate_conflicts(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    with pytest.raises(Conflict):
        run_store.create_run(run)


def test_get_run_not_found(run_store: RunStore) -> None:
    with pytest.raises(NotFound):
        run_store.get_run("run_does_not_exist")


def test_list_runs_ordered_newest_first(run_store: RunStore) -> None:
    r1 = _make_run()
    run_store.create_run(r1)
    time.sleep(0.01)
    r2 = _make_run()
    run_store.create_run(r2)

    runs = run_store.list_runs(limit=50)
    ids = [r.run_id for r in runs]
    assert ids.index(r2.run_id) < ids.index(r1.run_id)


def test_update_run_sets_fields_and_bumps_updated_at(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    before = run_store.get_run(run.run_id).updated_at

    time.sleep(0.01)
    run_store.update_run(run.run_id, status="running", error="oops")

    after = run_store.get_run(run.run_id)
    assert after.status == "running"
    assert after.error == "oops"
    assert after.updated_at > before


def test_update_run_not_found(run_store: RunStore) -> None:
    with pytest.raises(NotFound):
        run_store.update_run("run_does_not_exist", status="running")


def test_claim_run_picks_oldest_queued(run_store: RunStore) -> None:
    r1 = _make_run()
    run_store.create_run(r1)
    time.sleep(0.01)
    r2 = _make_run()
    run_store.create_run(r2)

    claimed = run_store.claim_run("worker-1", lease_s=60)
    assert claimed is not None
    assert claimed.run_id == r1.run_id
    assert claimed.status == "running"
    assert claimed.lease is not None
    assert claimed.lease.owner == "worker-1"


def test_claim_run_none_when_nothing_available(run_store: RunStore) -> None:
    run = _make_run(status="completed")
    run_store.create_run(run)
    assert run_store.claim_run("worker-1") is None


def test_claim_run_reclaims_after_lease_expiry(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    first = run_store.claim_run("worker-1", lease_s=1)
    assert first is not None
    time.sleep(1.2)

    second = run_store.claim_run("worker-2", lease_s=60)
    assert second is not None
    assert second.run_id == run.run_id
    assert second.lease.owner == "worker-2"


def test_claim_run_exclusivity_under_race(run_store: RunStore) -> None:
    """Exactly one of N claimers racing in threads wins the single queued run."""
    run = _make_run()
    run_store.create_run(run)

    n = 8
    winners: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def _claim(worker_id: str) -> None:
        barrier.wait()
        claimed = run_store.claim_run(worker_id, lease_s=60)
        if claimed is not None:
            with lock:
                winners.append(worker_id)

    threads = [threading.Thread(target=_claim, args=(f"worker-{i}",)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(winners) == 1


def test_heartbeat_extends_lease_and_returns_true_for_owner(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    run_store.claim_run("worker-1", lease_s=60)

    assert run_store.heartbeat(run.run_id, "worker-1", lease_s=120) is True


def test_heartbeat_returns_false_for_non_owner(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    run_store.claim_run("worker-1", lease_s=60)

    assert run_store.heartbeat(run.run_id, "worker-2", lease_s=120) is False


def test_release_clears_lease(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    run_store.claim_run("worker-1", lease_s=60)

    run_store.release(run.run_id, "worker-1")
    assert run_store.get_run(run.run_id).lease is None


def test_save_and_latest_plan(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    assert run_store.latest_plan(run.run_id) is None

    run_store.save_plan(_make_plan(run.run_id, version=1))
    run_store.save_plan(_make_plan(run.run_id, version=2))

    latest = run_store.latest_plan(run.run_id)
    assert latest is not None
    assert latest.version == 2


def test_save_plan_duplicate_version_conflicts(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    run_store.save_plan(_make_plan(run.run_id, version=1))
    with pytest.raises(Conflict):
        run_store.save_plan(_make_plan(run.run_id, version=1))


def test_save_get_update_and_list_steps(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    step2 = _make_step(run.run_id, seq=2)
    step1 = _make_step(run.run_id, seq=1)
    run_store.save_step(step2)
    run_store.save_step(step1)

    fetched = run_store.get_step(step1.step_id)
    assert fetched.step_id == step1.step_id
    assert fetched.title == step1.title

    run_store.update_step(step1.step_id, status="running", attempts=1)
    assert run_store.get_step(step1.step_id).status == "running"
    assert run_store.get_step(step1.step_id).attempts == 1

    ordered = run_store.steps(run.run_id)
    assert [s.seq for s in ordered] == [1, 2]


def test_get_step_not_found(run_store: RunStore) -> None:
    with pytest.raises(NotFound):
        run_store.get_step("step_does_not_exist")


def test_update_step_not_found(run_store: RunStore) -> None:
    with pytest.raises(NotFound):
        run_store.update_step("step_does_not_exist", status="running")


def test_save_step_duplicate_seq_conflicts(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    run_store.save_step(_make_step(run.run_id, seq=1))
    with pytest.raises(Conflict):
        run_store.save_step(_make_step(run.run_id, seq=1))


def test_log_event_returns_sequential_seq_and_events_orders_ascending(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    seq1 = run_store.log_event(run.run_id, "run_created")
    seq2 = run_store.log_event(run.run_id, "plan_created", payload={"version": 1})
    assert seq1 == 1
    assert seq2 == 2

    events = run_store.events(run.run_id)
    assert [e["seq"] for e in events] == [1, 2]
    assert events[1]["type"] == "plan_created"
    assert events[1]["payload"] == {"version": 1}

    after_first = run_store.events(run.run_id, after_seq=1)
    assert [e["seq"] for e in after_first] == [2]


def test_log_event_seq_unique_under_concurrent_threads(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    n_threads = 8
    per_thread = 5
    seqs: list[int] = []
    lock = threading.Lock()

    def _log(worker_id: str) -> None:
        for _ in range(per_thread):
            seq = run_store.log_event(run.run_id, "note", payload={"worker": worker_id})
            with lock:
                seqs.append(seq)

    threads = [threading.Thread(target=_log, args=(f"w{i}",)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(seqs) == n_threads * per_thread
    assert len(set(seqs)) == len(seqs)  # all unique
    assert sorted(seqs) == list(range(1, n_threads * per_thread + 1))


def test_update_run_to_terminal_status_sets_events_expire_at(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)
    run_store.log_event(run.run_id, "run_created")

    run_store.update_run(run.run_id, status="completed")

    if isinstance(run_store, InMemoryRunStore):
        pytest.skip("expire_at TTL is an Atlas-only mechanism; the fake has no TTL index")

    from portpilot.store.v2.atlas import AtlasRunStore

    assert isinstance(run_store, AtlasRunStore)
    doc = run_store._loop.run(run_store.async_store.events.find_one({"run_id": run.run_id}))
    assert doc is not None
    assert doc.get("expire_at") is not None


def test_put_get_and_list_artifacts_small(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    artifact_id = run_store.put_artifact(
        run.run_id, None, "report", {"ok": True, "detail": "small"}, name="r1"
    )
    fetched = run_store.get_artifact(artifact_id)
    assert fetched["artifact_id"] == artifact_id
    assert fetched["run_id"] == run.run_id
    assert fetched["kind"] == "report"
    assert fetched["content"] == {"ok": True, "detail": "small"}

    listed = run_store.list_artifacts(run.run_id)
    assert len(listed) == 1
    assert "content" not in listed[0]
    assert listed[0]["artifact_id"] == artifact_id

    by_kind = run_store.list_artifacts(run.run_id, kind="report")
    assert len(by_kind) == 1
    assert run_store.list_artifacts(run.run_id, kind="other") == []


def test_get_artifact_not_found(run_store: RunStore) -> None:
    with pytest.raises(NotFound):
        run_store.get_artifact("art_does_not_exist")


def test_put_artifact_gridfs_offload_for_large_content(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    # ~2 MB of JSON-able content, comfortably over the 1 MB GridFS threshold.
    big_text = "x" * (2 * 1024 * 1024)
    artifact_id = run_store.put_artifact(run.run_id, None, "log", {"text": big_text}, name="big")

    fetched = run_store.get_artifact(artifact_id)
    assert fetched["content"] == {"text": big_text}

    if isinstance(run_store, InMemoryRunStore):
        return

    from portpilot.store.v2.atlas import AtlasRunStore

    assert isinstance(run_store, AtlasRunStore)
    raw = run_store._loop.run(
        run_store.async_store.artifacts.find_one({"artifact_id": artifact_id})
    )
    assert raw is not None
    assert "gridfs_id" in raw
    assert "content" not in raw


def test_from_doc_fidelity_including_tz_aware_datetimes(run_store: RunStore) -> None:
    run = _make_run()
    run_store.create_run(run)

    fetched = run_store.get_run(run.run_id)
    assert fetched.created_at.tzinfo is not None
    assert fetched.updated_at.tzinfo is not None
    # Mongo stores millisecond precision; a round trip may lose sub-millisecond digits.
    assert abs((fetched.created_at - run.created_at).total_seconds()) < 0.001
    assert fetched.budgets == run.budgets
    assert fetched.usage == run.usage
