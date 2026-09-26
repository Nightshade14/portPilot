"""Manual test against the real Atlas cluster + real Voyage embeddings (lane brief:
"one test against the real cluster db `portpilot_mvp` with the real
`VoyageEmbedder`"). NOT collected by default -- run explicitly:

    uv run pytest tests/knowledge/test_live_atlas.py -m "live_atlas and live_voyage" -q

Never creates more than the 2 production indexes (`knowledge_text`, `knowledge_vec`
on `portpilot_mvp.knowledge`): checks `list_search_indexes` on the target collection
first and refuses if either is already present under 2 unrelated names would exceed
the M0 budget. Items carry `status="test"` and are deleted in a `finally` block, so no
test data is left behind.
"""

from __future__ import annotations

import uuid

import pytest
from dotenv import dotenv_values

from portpilot.core.models import KnowledgeItem, KnowledgeSource
from portpilot.knowledge.embedder import VoyageEmbedder
from portpilot.knowledge.indexes import TEXT_INDEX_NAME, VECTOR_INDEX_NAME, ensure_indexes
from portpilot.knowledge.store import AtlasKnowledgeStore

pytestmark = [pytest.mark.live_atlas, pytest.mark.live_voyage]

ENV_PATH = "/Users/satyamchatrola/codes/personal/portPilot/.env"


@pytest.fixture
def live_store():
    env = dotenv_values(ENV_PATH)
    uri = env.get("MONGODB_URI")
    voyage_key = env.get("VOYAGE_API_KEY")
    if not uri or not voyage_key:
        pytest.skip("MONGODB_URI / VOYAGE_API_KEY not available in .env")

    db_name = env.get("MVP_MONGODB_DB", "portpilot_mvp")
    embedder = VoyageEmbedder(api_key=voyage_key)

    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = client[db_name]

    # Refuse to proceed if the collection already carries search indexes under
    # names other than the 2 production ones -- never exceed the M0 budget.
    if "knowledge" in db.list_collection_names():
        existing_names = {idx["name"] for idx in db["knowledge"].list_search_indexes()}
        unexpected = existing_names - {TEXT_INDEX_NAME, VECTOR_INDEX_NAME}
        if unexpected:
            client.close()
            pytest.fail(f"Unexpected search indexes already present: {sorted(unexpected)}")

    store = AtlasKnowledgeStore(uri, db_name, embedder)
    try:
        yield store
    finally:
        store.close()
        client.close()


def test_ensure_indexes_and_upsert_search_delete_on_real_cluster(live_store):
    ensure_indexes(live_store.db, live_store.embedder.dims, wait=True, timeout_s=180)
    index_names = {idx["name"] for idx in live_store.coll.list_search_indexes()}
    assert index_names == {TEXT_INDEX_NAME, VECTOR_INDEX_NAME}, (
        f"expected exactly the 2 production indexes, found {sorted(index_names)}"
    )

    marker = uuid.uuid4().hex[:8]
    item_id = f"livetest_{marker}"
    inserted_ids: list[str] = []
    try:
        item = KnowledgeItem(
            id=item_id,
            kind="lesson",
            title=f"Live test lesson {marker}",
            body="This is a throwaway lesson used only to verify the live Atlas + "
            "Voyage path end to end. Safe to ignore if you see it outside a test run.",
            tags=["live-test"],
            status="test",
            sources=[KnowledgeSource(repo_url="https://example.invalid/live-test")],
        )
        upserted_id = live_store.upsert(item, dedupe=False)
        inserted_ids.append(upserted_id)
        assert upserted_id == item_id

        fetched = live_store.get(item_id)
        assert fetched.status == "test"
        assert fetched.title == item.title

        # give mongot a moment to index the freshly inserted doc before searching
        import time

        hits = []
        deadline = time.monotonic() + 15
        while not hits and time.monotonic() < deadline:
            hits = live_store.search(
                f"live test lesson {marker}",
                kinds=["lesson"],
                mode="text",
                filters={"status": "test"},
                limit=5,
            )
            if not hits:
                time.sleep(1)
        assert any(h.item.id == item_id for h in hits), (
            "inserted test item not found via text search"
        )

        vector_hits = []
        deadline = time.monotonic() + 15
        while not vector_hits and time.monotonic() < deadline:
            vector_hits = live_store.search(
                f"live test lesson {marker} throwaway",
                kinds=["lesson"],
                mode="vector",
                filters={"status": "test"},
                limit=5,
            )
            if not vector_hits:
                time.sleep(1)
        assert any(h.item.id == item_id for h in vector_hits), (
            "inserted test item not found via vector search"
        )
    finally:
        for iid in inserted_ids:
            live_store.coll.delete_one({"_id": iid})
        remaining = live_store.coll.find_one({"_id": item_id})
        assert remaining is None, "failed to clean up live test document"
