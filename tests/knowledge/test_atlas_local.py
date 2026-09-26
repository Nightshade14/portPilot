"""Integration tests against `mongodb/mongodb-atlas-local:latest` on 127.0.0.1:27019.

Uses `PORTPILOT_TEST_ATLAS_LOCAL_URI` and `FakeEmbedder(dims=64)` with indexes built
for 64 dims (lane brief). Start the container yourself first:

    docker run -d --name pp-test-k-atlaslocal -p 127.0.0.1:27019:27017 \
        mongodb/mongodb-atlas-local:latest

Run:

    PORTPILOT_TEST_ATLAS_LOCAL_URI=mongodb://127.0.0.1:27019/?directConnection=true \
        uv run pytest tests/knowledge -m atlas_local

Each test gets its own throwaway database (dropped in teardown) so tests don't
interfere with each other's dedupe/search state.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
from pymongo import MongoClient

from portpilot.core.fakes import FakeEmbedder
from portpilot.core.models import KnowledgeItem, KnowledgeSource
from portpilot.knowledge.indexes import ensure_indexes
from portpilot.knowledge.store import AtlasKnowledgeStore

pytestmark = pytest.mark.atlas_local

DIMS = 64


def _uri() -> str | None:
    return os.environ.get("PORTPILOT_TEST_ATLAS_LOCAL_URI")


@pytest.fixture
def store():
    uri = _uri()
    if not uri:
        pytest.skip("PORTPILOT_TEST_ATLAS_LOCAL_URI not set")
    db_name = f"pp_test_k_{uuid.uuid4().hex[:8]}"
    embedder = FakeEmbedder(dims=DIMS)
    ks = AtlasKnowledgeStore(uri, db_name, embedder, hybrid="rankfusion")
    ensure_indexes(ks.db, DIMS, wait=True, timeout_s=60, poll_interval_s=1)
    try:
        yield ks
    finally:
        client: MongoClient = ks.client
        client.drop_database(db_name)
        ks.close()


def _item(item_id: str, kind: str, title: str, body: str, **kw) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        kind=kind,
        title=title,
        body=body,
        sources=[KnowledgeSource(run_id="run_test")],
        **kw,
    )


def _search_until(store, *args, timeout_s: float = 10.0, **kwargs):
    """mongot indexes asynchronously: `$search`/`$vectorSearch` can lag a live insert
    by ~1s even after the index itself is `queryable`. Retry briefly instead of a
    fixed sleep, so the suite stays fast when mongot has already caught up."""
    deadline = time.monotonic() + timeout_s
    hits = store.search(*args, **kwargs)
    while not hits and time.monotonic() < deadline:
        time.sleep(0.3)
        hits = store.search(*args, **kwargs)
    return hits


def test_ensure_indexes_is_idempotent(store):
    report_again = ensure_indexes(store.db, DIMS, wait=True, timeout_s=60, poll_interval_s=1)
    assert report_again["created"] == []
    assert report_again["updated"] == []
    assert set(report_again["unchanged"]) == {"knowledge_text", "knowledge_vec"}


def test_exact_keyword_query_finds_item_in_text_mode(store):
    store.upsert(
        _item("k1", "gotcha", "Retry on 429", "Use exponential backoff for rate limits."),
        dedupe=False,
    )
    store.upsert(
        _item("k2", "gotcha", "Unrelated", "Something about docker networking."), dedupe=False
    )

    hits = _search_until(store, "exponential backoff", kinds=["gotcha"], mode="text", limit=5)

    assert any(h.item.id == "k1" for h in hits)
    assert all(h.via == "text" for h in hits)


def test_shared_words_query_finds_item_in_vector_mode(store):
    # FakeEmbedder is bag-of-words hashing: sharing words -> close vectors.
    store.upsert(
        _item("v1", "lesson", "Trivy scans tarballs", "docker archive format works best"),
        dedupe=False,
    )
    store.upsert(
        _item("v2", "lesson", "Unrelated lesson", "totally different content here"), dedupe=False
    )

    hits = _search_until(
        store,
        "trivy scans tarballs docker archive format",
        kinds=["lesson"],
        mode="vector",
        limit=5,
    )

    assert hits
    assert hits[0].item.id == "v1"
    assert all(h.via == "vector" for h in hits)


def test_hybrid_returns_union_ranked_with_via_both_when_found_both_ways(store):
    # A doc found by both branches for a query matching its exact words (text) and
    # therefore also close in the bag-of-words vector space (vector).
    store.upsert(
        _item("h1", "lesson", "Retry on 429 with backoff", "exponential backoff for rate limits"),
        dedupe=False,
    )
    store.upsert(
        _item("h2", "lesson", "Completely different", "nothing overlapping at all"), dedupe=False
    )

    hits = _search_until(store, "retry 429 backoff", kinds=["lesson"], mode="hybrid", limit=5)

    assert hits
    top_ids = [h.item.id for h in hits]
    assert "h1" in top_ids
    h1_hit = next(h for h in hits if h.item.id == "h1")
    assert h1_hit.via in {"both", "text", "vector"}  # server-dependent scoreDetails shape


def test_kind_and_facet_filters_apply(store):
    store.upsert(
        _item(
            "f1",
            "gotcha",
            "Python gotcha",
            "watch out for this python issue",
            facets={"language": "python"},
        ),
        dedupe=False,
    )
    store.upsert(
        _item(
            "f2",
            "gotcha",
            "JS gotcha",
            "watch out for this python issue too",
            facets={"language": "javascript"},
        ),
        dedupe=False,
    )

    hits = _search_until(
        store,
        "watch out python issue",
        kinds=["gotcha"],
        mode="vector",
        filters={"facets.language": "python"},
        limit=5,
    )

    assert hits
    assert all(h.item.facets.get("language") == "python" for h in hits)


def test_dedupe_merges_near_duplicate_document(store):
    first = _item("d1", "lesson", "Same lesson text", "identical body content for dedupe")
    dup = _item("d2", "lesson", "Same lesson text", "identical body content for dedupe")

    id1 = store.upsert(first, dedupe=True)
    # Dedupe's own duplicate-check is a $vectorSearch, subject to the same mongot
    # indexing lag as a plain search -- wait for the first doc to become findable
    # before upserting the near-duplicate, or the merge check can race a fresh insert.
    _search_until(store, "identical body content dedupe", kinds=["lesson"], mode="vector", limit=1)
    id2 = store.upsert(dup, dedupe=True)

    assert id1 == id2  # merged into the same document
    merged = store.get(id1)
    assert merged.seen_count == 2
    assert len(merged.sources) == 2


def test_dedupe_does_not_merge_distinct_kinds(store):
    a = _item("a1", "lesson", "Same text", "identical body content here")
    b = _item("b1", "gotcha", "Same text", "identical body content here")

    id_a = store.upsert(a, dedupe=True)
    _search_until(store, "identical body content here", kinds=["lesson"], mode="vector", limit=1)
    id_b = store.upsert(b, dedupe=True)

    assert id_a != id_b
    assert store.get(id_a).seen_count == 1
    assert store.get(id_b).seen_count == 1


def test_list_items_and_set_status(store):
    store.upsert(_item("l1", "memory", "M1", "body one"), dedupe=False)
    store.upsert(_item("l2", "memory", "M2", "body two"), dedupe=False)

    items = store.list_items(kinds=["memory"])
    assert {i.id for i in items} == {"l1", "l2"}

    store.set_status("l1", "archived")
    assert store.get("l1").status == "archived"


def test_search_never_returns_embedding_field(store):
    store.upsert(_item("e1", "lesson", "Has embedding", "some body text"), dedupe=False)
    hits = _search_until(store, "some body text", mode="text", limit=5)
    for hit in hits:
        assert "embedding" not in hit.item.to_doc()
