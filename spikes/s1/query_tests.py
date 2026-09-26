"""Spike S1 goal 2: insert fixture docs, run $search, $vectorSearch, $rankFusion
(and its fallback), determine rankFusion + $vectorSearch/$search compatibility on 8.0.32.

Run: uv run python spikes/s1/query_tests.py
"""

from __future__ import annotations

import hashlib
import time

from dotenv import dotenv_values
from hybrid import build_manual_rrf_pipeline_for, rank_fusion_pipeline
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

ENV_PATH = "/Users/satyamchatrola/codes/personal/portPilot/.env"
DB_NAME = "portpilot_spike"
COLL_NAME = "knowledge_spike"
DIMS = 1024

TEXT_INDEX_DEF = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "title": {"type": "string", "analyzer": "lucene.standard"},
            "body": {"type": "string", "analyzer": "lucene.standard"},
            "tags": {"type": "token"},
        },
    }
}

VECTOR_INDEX_DEF = {
    "fields": [
        {"type": "vector", "path": "embedding", "numDimensions": DIMS, "similarity": "cosine"},
        {"type": "filter", "path": "kind"},
        {"type": "filter", "path": "status"},
        {"type": "filter", "path": "facets.language"},
    ]
}


def hash_seeded_unit_vector(seed: str, dims: int = DIMS) -> list[float]:
    """Deterministic pseudo-random unit vector from a string seed (no numpy dependency)."""
    vec = []
    counter = 0
    while len(vec) < dims:
        h = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        for i in range(0, len(h), 4):
            if len(vec) >= dims:
                break
            chunk = h[i : i + 4]
            val = int.from_bytes(chunk, "big") / 2**32 - 0.5
            vec.append(val)
        counter += 1
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


def build_fixture_docs() -> list[dict]:
    docs = [
        {"title": "Retry on 429 with exponential backoff", "kind": "gotcha", "seed": "retry-429"},
        {
            "title": "Always drop the M0 search index in finally",
            "kind": "gotcha",
            "seed": "m0-drop-index",
        },
        {
            "title": "Use dotenv_values, never os.environ for secrets",
            "kind": "lesson",
            "seed": "dotenv-secrets",
        },
        {
            "title": "Pin exact dependency versions with uv add",
            "kind": "lesson",
            "seed": "pin-deps",
        },
        {
            "title": "httpx client for calling REST embedding APIs",
            "kind": "tool_card",
            "seed": "httpx-client",
        },
        {
            "title": "pymongo SearchIndexModel for Atlas Search",
            "kind": "tool_card",
            "seed": "search-index-model",
        },
        {
            "title": "Flask to Hono migration preserves route behavior",
            "kind": "lesson",
            "seed": "flask-hono",
        },
        {
            "title": "Docker atlas-local image needs directConnection",
            "kind": "gotcha",
            "seed": "atlas-local-direct",
        },
        # Paraphrase pair 1: nearby vectors (same seed prefix -> similar-but-not-identical seed)
        {
            "title": "Collection must exist before creating a search index",
            "kind": "gotcha",
            "seed": "collection-exists",
        },
        {
            "title": "Search index creation requires the collection to already exist",
            "kind": "gotcha",
            "seed": "collection-exists",
        },
        # Paraphrase pair 2
        {
            "title": "rankFusion needs MongoDB 8.1 or newer",
            "kind": "gotcha",
            "seed": "rankfusion-version",
        },
        {
            "title": "Hybrid rankFusion stage requires server version 8.1+",
            "kind": "gotcha",
            "seed": "rankfusion-version",
        },
    ]
    out = []
    for i, d in enumerate(docs):
        out.append(
            {
                "title": d["title"],
                "body": d["title"] + " -- spike s1 fixture body text for search matching.",
                "kind": d["kind"],
                "status": "active",
                "tags": [d["kind"], "spike-s1"],
                "facets": {"language": "en"},
                "embedding": hash_seeded_unit_vector(d["seed"]),
                "_fixture_index": i,
            }
        )
    return out


def poll_until_queryable(coll, names: list[str], timeout_s: int = 300, interval_s: int = 5) -> dict:
    start = time.monotonic()
    remaining = set(names)
    elapsed: dict[str, float] = {}
    while remaining and (time.monotonic() - start) < timeout_s:
        for idx in coll.list_search_indexes():
            if idx.get("name") in remaining and idx.get("queryable"):
                elapsed[idx["name"]] = time.monotonic() - start
                remaining.discard(idx["name"])
        if remaining:
            time.sleep(interval_s)
    return {"elapsed_s": elapsed, "timed_out": bool(remaining)}


def main() -> None:
    env = dotenv_values(ENV_PATH)
    client = MongoClient(env["MONGODB_URI"])
    db = client[DB_NAME]
    coll = db[COLL_NAME]

    result: dict = {}
    try:
        if COLL_NAME not in db.list_collection_names():
            db.create_collection(COLL_NAME)

        docs = build_fixture_docs()
        ins = coll.insert_many(docs)
        result["inserted_count"] = len(ins.inserted_ids)

        models = [
            SearchIndexModel(definition=TEXT_INDEX_DEF, name="knowledge_text", type="search"),
            SearchIndexModel(
                definition=VECTOR_INDEX_DEF, name="knowledge_vec", type="vectorSearch"
            ),
        ]
        coll.create_search_indexes(models)
        result["poll"] = poll_until_queryable(coll, ["knowledge_text", "knowledge_vec"])

        # 1. $search text query
        text_pipeline = [
            {
                "$search": {
                    "index": "knowledge_text",
                    "text": {"query": "retry backoff", "path": ["title", "body"]},
                }
            },
            {"$limit": 5},
            {"$project": {"_id": 0, "title": 1, "score": {"$meta": "searchScore"}}},
        ]
        result["search_text_query"] = list(coll.aggregate(text_pipeline))

        # 2. $vectorSearch with kind filter
        qvec = hash_seeded_unit_vector(
            "collection-exists"
        )  # should match the paraphrase pair strongly
        vec_pipeline = [
            {
                "$vectorSearch": {
                    "index": "knowledge_vec",
                    "path": "embedding",
                    "queryVector": qvec,
                    "numCandidates": 50,
                    "limit": 5,
                    "filter": {"kind": {"$eq": "gotcha"}},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "title": 1,
                    "kind": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        result["vector_search_with_filter"] = list(coll.aggregate(vec_pipeline))

        # 3a. Native $rankFusion -- determine exact compatibility on 8.0.32
        try:
            rf_pipeline = rank_fusion_pipeline("retry backoff", qvec, kind_filter=None, limit=5)
            result["rank_fusion_result"] = list(coll.aggregate(rf_pipeline))
            result["rank_fusion_supported"] = True
        except OperationFailure as e:
            result["rank_fusion_supported"] = False
            result["rank_fusion_error"] = {
                "code": e.code,
                "codeName": e.details.get("codeName") if e.details else None,
                "errmsg": str(e),
            }

        # 3b. Manual RRF fallback -- must work regardless of server version
        rrf_pipeline = build_manual_rrf_pipeline_for(
            COLL_NAME, "retry backoff", qvec, kind_filter=None, k=60, limit=5
        )
        result["manual_rrf_result"] = list(coll.aggregate(rrf_pipeline))

    finally:
        db.drop_collection(COLL_NAME)
        result["dropped_collection"] = True
        result["remaining_indexes_after_drop"] = [i.get("name") for i in coll.list_search_indexes()]

    import json

    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
