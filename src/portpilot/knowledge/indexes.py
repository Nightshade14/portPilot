"""Atlas Search + Vector Search index management for `<db>.knowledge` (lane brief step 2).

Definitions verbatim from spike S1 (docs/spikes/S1_ATLAS.md), with the vector index's
`numDimensions` parameterized (S1 hardcoded 1024 for voyage-4's default) and its filter
fields extended per the lane brief: `kind`, `status`, `facets.language`,
`facets.framework`, `facets.ecosystem`, `facets.tool`. `kind` is also a `token` field on
the text index so `$search` can filter by it (`knowledge_text` in S1 only covered
title/body/tags).

M0 allows 3 search indexes cluster-wide; this module only ever names these 2.
"""

from __future__ import annotations

import time
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.operations import SearchIndexModel

TEXT_INDEX_NAME = "knowledge_text"
VECTOR_INDEX_NAME = "knowledge_vec"
VECTOR_FILTER_FIELDS = (
    "kind",
    "status",
    "facets.language",
    "facets.framework",
    "facets.ecosystem",
    "facets.tool",
)


def text_index_definition() -> dict[str, Any]:
    return {
        "mappings": {
            "dynamic": False,
            "fields": {
                "title": {"type": "string", "analyzer": "lucene.standard"},
                "body": {"type": "string", "analyzer": "lucene.standard"},
                "tags": {"type": "token"},
                "kind": {"type": "token"},
            },
        }
    }


def vector_index_definition(dims: int) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"},
    ]
    fields.extend({"type": "filter", "path": path} for path in VECTOR_FILTER_FIELDS)
    return {"fields": fields}


def _existing_by_name(coll: Collection) -> dict[str, dict[str, Any]]:
    return {idx["name"]: idx for idx in coll.list_search_indexes()}


def _definition_changed(existing: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Best-effort comparison: Atlas materializes extra keys (e.g. autoEmbed's
    numDimensions/similarity/quantization defaults per S1), so compare only the keys
    we actually submitted."""
    current = existing.get("latestDefinition", existing.get("definition", {}))

    def _subset_equal(sub: Any, full: Any) -> bool:
        if isinstance(sub, dict):
            if not isinstance(full, dict):
                return False
            return all(k in full and _subset_equal(v, full[k]) for k, v in sub.items())
        if isinstance(sub, list):
            if not isinstance(full, list) or len(sub) != len(full):
                return False
            return all(_subset_equal(a, b) for a, b in zip(sub, full, strict=True))
        return sub == full

    return not _subset_equal(wanted, current)


def ensure_indexes(
    db: Database, dims: int, *, wait: bool = True, timeout_s: int = 180, poll_interval_s: int = 3
) -> dict[str, Any]:
    """Idempotent: creates `knowledge_text`/`knowledge_vec` on `db.knowledge` if
    missing, updates either whose stored definition differs from what we want, and
    (if `wait`) polls `list_search_indexes()` until both report `queryable: True`.

    Never creates indexes beyond these two named ones. Returns a report dict with
    `created`, `updated`, `unchanged` name lists and (if waited) `queryable_after_s`.
    """
    coll = db["knowledge"]
    if "knowledge" not in db.list_collection_names():
        db.create_collection("knowledge")

    wanted = {
        TEXT_INDEX_NAME: ("search", text_index_definition()),
        VECTOR_INDEX_NAME: ("vectorSearch", vector_index_definition(dims)),
    }
    existing = _existing_by_name(coll)

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []

    to_create: list[SearchIndexModel] = []
    for name, (kind, definition) in wanted.items():
        if name not in existing:
            to_create.append(SearchIndexModel(definition=definition, name=name, type=kind))
        elif _definition_changed(existing[name], definition):
            coll.update_search_index(name, definition)
            updated.append(name)
        else:
            unchanged.append(name)

    if to_create:
        coll.create_search_indexes(to_create)
        created.extend(m.document["name"] for m in to_create)

    report: dict[str, Any] = {"created": created, "updated": updated, "unchanged": unchanged}

    if wait and (created or updated):
        report["queryable_after_s"] = _poll_until_queryable(
            coll, list(wanted), timeout_s=timeout_s, poll_interval_s=poll_interval_s
        )

    return report


def _poll_until_queryable(
    coll: Collection, names: list[str], *, timeout_s: int, poll_interval_s: int
) -> dict[str, float]:
    start = time.monotonic()
    remaining = set(names)
    elapsed: dict[str, float] = {}
    while remaining and (time.monotonic() - start) < timeout_s:
        for idx in coll.list_search_indexes():
            if idx.get("name") in remaining and idx.get("queryable"):
                elapsed[idx["name"]] = time.monotonic() - start
                remaining.discard(idx["name"])
        if remaining:
            time.sleep(poll_interval_s)
    for name in remaining:
        elapsed[name] = -1.0  # timed out
    return elapsed


def list_search_index_names(coll: Collection) -> list[str]:
    return [idx.get("name") for idx in coll.list_search_indexes()]
