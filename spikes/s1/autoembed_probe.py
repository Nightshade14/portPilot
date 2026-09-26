"""Spike S1 goal 4: does an autoEmbed vector index work on Atlas M0?

Docs conclusion (see docs/spikes/S1_ATLAS.md): Automated Embedding is
documented as available only for self-managed MongoDB Search/Vector Search
(Docker/tarball/package manager, or the Kubernetes Operator with MongoDB 8.2+
Community Edition) -- not for Atlas at all, any tier. This script empirically
confirms that by attempting to create one on the real M0 cluster.

Run: uv run python spikes/s1/autoembed_probe.py
"""

from __future__ import annotations

from dotenv import dotenv_values
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

ENV_PATH = "/Users/satyamchatrola/codes/personal/portPilot/.env"
DB_NAME = "portpilot_spike"
COLL_NAME = "knowledge_spike"

AUTOEMBED_DEF = {
    "fields": [
        {"type": "autoEmbed", "modality": "text", "path": "body", "model": "voyage-4"},
    ]
}


def main() -> None:
    env = dotenv_values(ENV_PATH)
    client = MongoClient(env["MONGODB_URI"])
    db = client[DB_NAME]
    coll = db[COLL_NAME]

    result: dict = {}
    try:
        if COLL_NAME not in db.list_collection_names():
            db.create_collection(COLL_NAME)

        model = SearchIndexModel(
            definition=AUTOEMBED_DEF, name="knowledge_autoembed", type="vectorSearch"
        )
        try:
            coll.create_search_indexes([model])
            result["autoembed_create_accepted"] = True

            import time

            start = time.monotonic()
            final_state = None
            while time.monotonic() - start < 90:
                idxs = {i["name"]: i for i in coll.list_search_indexes()}
                idx = idxs.get("knowledge_autoembed")
                if idx is None:
                    final_state = {"vanished": True}
                    break
                status = idx.get("status")
                queryable = idx.get("queryable")
                if status in ("READY", "FAILED") or queryable:
                    final_state = {
                        "status": status,
                        "queryable": queryable,
                        "raw": {k: v for k, v in idx.items() if k != "latestDefinition"},
                    }
                    break
                time.sleep(3)
            else:
                final_state = {"timed_out_polling": True}
            result["final_state"] = final_state
        except OperationFailure as e:
            result["autoembed_create_accepted"] = False
            result["error"] = {
                "code": e.code,
                "codeName": e.details.get("codeName") if e.details else None,
                "errmsg": str(e),
            }
    finally:
        db.drop_collection(COLL_NAME)
        result["remaining_indexes_after_drop"] = [i.get("name") for i in coll.list_search_indexes()]

    print(result)


if __name__ == "__main__":
    main()
