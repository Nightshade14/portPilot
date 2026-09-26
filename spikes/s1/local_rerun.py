"""Spike S1 goal 5 step 4: rerun goals 1 and 2 against mongodb-atlas-local.

Run: uv run python spikes/s1/local_rerun.py
"""

from __future__ import annotations

import json
import time

from hybrid import build_manual_rrf_pipeline_for, rank_fusion_pipeline
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel
from query_tests import build_fixture_docs, hash_seeded_unit_vector

LOCAL_URI = "mongodb://127.0.0.1:27019/?directConnection=true"
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


def poll_until_queryable(coll, names, timeout_s=120, interval_s=2):
    start = time.monotonic()
    remaining = set(names)
    elapsed = {}
    while remaining and (time.monotonic() - start) < timeout_s:
        for idx in coll.list_search_indexes():
            if idx.get("name") in remaining and idx.get("queryable"):
                elapsed[idx["name"]] = time.monotonic() - start
                remaining.discard(idx["name"])
        if remaining:
            time.sleep(interval_s)
    return {"elapsed_s": elapsed, "timed_out": bool(remaining)}


def main():
    client = MongoClient(LOCAL_URI, serverSelectionTimeoutMS=10000)
    db = client[DB_NAME]
    coll = db[COLL_NAME]

    result = {"server_version": client.server_info()["version"]}
    try:
        if COLL_NAME not in db.list_collection_names():
            db.create_collection(COLL_NAME)

        docs = build_fixture_docs()
        coll.insert_many(docs)

        models = [
            SearchIndexModel(definition=TEXT_INDEX_DEF, name="knowledge_text", type="search"),
            SearchIndexModel(
                definition=VECTOR_INDEX_DEF, name="knowledge_vec", type="vectorSearch"
            ),
        ]
        coll.create_search_indexes(models)
        result["poll"] = poll_until_queryable(coll, ["knowledge_text", "knowledge_vec"])

        result["search_text_query"] = list(
            coll.aggregate(
                [
                    {
                        "$search": {
                            "index": "knowledge_text",
                            "text": {"query": "retry backoff", "path": ["title", "body"]},
                        }
                    },
                    {"$limit": 5},
                    {"$project": {"_id": 0, "title": 1, "score": {"$meta": "searchScore"}}},
                ]
            )
        )

        qvec = hash_seeded_unit_vector("collection-exists")
        result["vector_search_with_filter"] = list(
            coll.aggregate(
                [
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
            )
        )

        try:
            rf_pipeline = rank_fusion_pipeline("retry backoff", qvec, limit=5)
            result["rank_fusion_result"] = list(coll.aggregate(rf_pipeline))
            result["rank_fusion_supported_locally"] = True
        except OperationFailure as e:
            result["rank_fusion_supported_locally"] = False
            result["rank_fusion_error"] = str(e)

        rrf_pipeline = build_manual_rrf_pipeline_for(COLL_NAME, "retry backoff", qvec, limit=5)
        result["manual_rrf_result"] = list(coll.aggregate(rrf_pipeline))

    finally:
        db.drop_collection(COLL_NAME)
        result["remaining_indexes_after_drop"] = [i.get("name") for i in coll.list_search_indexes()]

    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
