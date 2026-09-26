"""Spike S1 goal 1: create/poll/drop Atlas Search + Vector Search indexes on the real M0 cluster.

Run: uv run python spikes/s1/indexes.py
"""

from __future__ import annotations

import time

from dotenv import dotenv_values
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

ENV_PATH = "/Users/satyamchatrola/codes/personal/portPilot/.env"
DB_NAME = "portpilot_spike"
COLL_NAME = "knowledge_spike"

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
        {
            "type": "vector",
            "path": "embedding",
            "numDimensions": 1024,
            "similarity": "cosine",
        },
        {"type": "filter", "path": "kind"},
        {"type": "filter", "path": "status"},
        {"type": "filter", "path": "facets.language"},
    ]
}


def get_client() -> MongoClient:
    env = dotenv_values(ENV_PATH)
    uri = env.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI not set in .env")
    return MongoClient(uri)


def redact(uri: str) -> str:
    if "@" in uri:
        scheme, rest = uri.split("://", 1)
        _creds, host = rest.split("@", 1)
        return f"{scheme}://***:***@{host}"
    return uri


def poll_until_queryable(coll, names: list[str], timeout_s: int = 300, interval_s: int = 5) -> dict:
    """Poll list_search_indexes() until all named indexes report queryable=True."""
    start = time.monotonic()
    elapsed_by_name: dict[str, float] = {}
    remaining = set(names)
    last_status: dict[str, str] = {}
    while remaining and (time.monotonic() - start) < timeout_s:
        for idx in coll.list_search_indexes():
            name = idx.get("name")
            if name in remaining:
                last_status[name] = idx.get("status")
                if idx.get("queryable"):
                    elapsed_by_name[name] = time.monotonic() - start
                    remaining.discard(name)
        if remaining:
            time.sleep(interval_s)
    for name in remaining:
        elapsed_by_name[name] = -1.0  # timed out
    return {"elapsed_s": elapsed_by_name, "last_status": last_status, "timed_out": bool(remaining)}


def existing_search_index_names(coll) -> list[str]:
    return [idx.get("name") for idx in coll.list_search_indexes()]


def main() -> None:
    client = get_client()
    db = client[DB_NAME]
    coll = db[COLL_NAME]

    result: dict = {"db": DB_NAME, "collection": COLL_NAME}

    try:
        # create_search_indexes fails with NamespaceNotFound if the collection
        # doesn't exist yet -- Atlas Search indexes can't be created on a
        # not-yet-materialized collection.
        if COLL_NAME not in db.list_collection_names():
            db.create_collection(COLL_NAME)
            result["created_collection_first"] = True

        pre_existing = existing_search_index_names(coll)
        result["pre_existing_indexes_in_target_collection"] = pre_existing

        models = [
            SearchIndexModel(definition=TEXT_INDEX_DEF, name="knowledge_text", type="search"),
            SearchIndexModel(
                definition=VECTOR_INDEX_DEF, name="knowledge_vec", type="vectorSearch"
            ),
        ]

        try:
            created_names = coll.create_search_indexes(models)
            result["created_names"] = created_names
        except Exception as e:
            msg = str(e)
            result["create_error"] = msg
            if "limit" in msg.lower() or "maximum" in msg.lower() or "quota" in msg.lower():
                # Per brief: stop, list existing search index names cluster-wide, report.
                result["limit_hit"] = True
                result["existing_after_limit_error"] = existing_search_index_names(coll)
                print(result)
                return
            raise

        poll_result = poll_until_queryable(coll, ["knowledge_text", "knowledge_vec"])
        result["poll_result"] = poll_result

    finally:
        # Always drop the collection to free the index slots on M0.
        try:
            db.drop_collection(COLL_NAME)
            result["dropped_collection"] = True
        except Exception as e:  # noqa: BLE001
            result["drop_error"] = str(e)

        remaining = existing_search_index_names(coll)
        result["remaining_indexes_after_drop"] = remaining

    print(result)


if __name__ == "__main__":
    main()
