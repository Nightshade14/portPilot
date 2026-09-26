"""Smoke tests for the reference fakes in portpilot.core.fakes."""

from __future__ import annotations

import shutil
import uuid
from datetime import timedelta

from portpilot.core.config import REPO_ROOT
from portpilot.core.fakes import (
    InMemoryKnowledgeStore,
    InMemoryRunStore,
    InMemoryToolStore,
    LocalSandboxManager,
)
from portpilot.core.models import KnowledgeItem, Lease, Run, ShortTermPlan, ToolRecord, utcnow


def test_run_store_lease_is_exclusive_and_reclaimable():
    store = InMemoryRunStore()
    store.create_run(Run(run_id="r1", repo_url="u", goal="g"))
    assert store.claim_run("w1").run_id == "r1"
    assert store.claim_run("w2") is None
    assert store.heartbeat("r1", "w1") and not store.heartbeat("r1", "w2")
    store.update_run("r1", lease=Lease("w1", utcnow() - timedelta(seconds=1)))
    assert store.claim_run("w2").lease.owner == "w2"


def test_run_store_steps_events_artifacts():
    store = InMemoryRunStore()
    store.create_run(Run(run_id="r1", repo_url="u", goal="g"))
    store.save_step(ShortTermPlan("s2", "r1", 2, "p1", "b", "o"))
    store.save_step(ShortTermPlan("s1", "r1", 1, "p1", "a", "o"))
    store.update_step("s1", status="done")
    assert [s.step_id for s in store.steps("r1")] == ["s1", "s2"]
    assert store.get_step("s1").status == "done"
    assert store.log_event("r1", "note") == 1 and store.log_event("r1", "note") == 2
    assert [e["seq"] for e in store.events("r1", after_seq=1)] == [2]
    aid = store.put_artifact("r1", "s1", "report", {"x": 1})
    assert store.get_artifact(aid)["content"] == {"x": 1}
    assert "content" not in store.list_artifacts("r1")[0]


def test_tool_store_active_version_and_stats():
    store = InMemoryToolStore()
    for v, status in ((1, "active"), (2, "candidate")):
        store.save(ToolRecord("audit", v, "d", "w", {}, {}, {"main.py": ""}, status=status))
    assert store.get("audit").version == 1 and store.next_version("audit") == 3
    store.record_use("audit", 1, "r1", ok=False)
    assert store.get("audit", 1).stats.failure_rate == 1.0


def test_knowledge_store_modes_and_dedupe():
    ks = InMemoryKnowledgeStore()
    a = ks.upsert(KnowledgeItem("k1", "gotcha", "zod returns 400", "use a custom hook for 422"))
    ks.upsert(KnowledgeItem("k2", "lesson", "trivy scans tarballs", "use docker-archive format"))
    assert (
        ks.upsert(KnowledgeItem("k3", "gotcha", "zod returns 400", "use a custom hook for 422"))
        == a
    )
    assert ks.get(a).seen_count == 2
    assert ks.search("trivy tarball", mode="text")[0].item.id == "k2"
    assert ks.search("zod 422", kinds=["gotcha"])[0].item.id == "k1"


def test_local_sandbox_commit_restore():
    # Under the repo (gitignored runs/): git in this environment cannot use $TMPDIR.
    root = REPO_ROOT / "runs" / "_pytest" / uuid.uuid4().hex[:8]
    sbx = LocalSandboxManager(root)
    sbx.ensure("r1")
    sbx.write_file("r1", "/workspace/repo/a.txt", "one")
    sha = sbx.commit("r1", "one")
    sbx.write_file("r1", "/workspace/repo/a.txt", "two")
    assert sbx.exec("r1", "cat a.txt").stdout == "two"
    sbx.restore("r1", sha)
    assert sbx.read_file("r1", "/workspace/repo/a.txt") == "one"
    assert sbx.export_archive("r1")[:2] == b"\x1f\x8b"
    shutil.rmtree(root, ignore_errors=True)


def test_local_sandbox_returns_a_strands_environment():
    sandbox = LocalSandboxManager(REPO_ROOT).sandbox("r1")

    assert type(sandbox).__name__ == "NotASandboxLocalEnvironment"
