"""AtlasKnowledgeStore: `core.interfaces.KnowledgeStore` on `<db>.knowledge` (lane brief step 3).

Sync client choice: plain `pymongo.MongoClient` (brief step 3 offers this as an
alternative to v0's async-loop-on-a-thread `store/atlas.py` pattern "if simpler").
`core.interfaces` documents every method as synchronous and pymongo's sync
`MongoClient` already manages its own connection pool and background monitoring
thread, so a second event loop would add complexity (a dedicated thread + run_coroutine
plumbing) without a benefit here: this store issues one aggregation/command per call,
never streams, and is called from worker threads, not from inside a running asyncio
loop that would need to avoid blocking. If a future lane needs true async fan-out,
swap in `AsyncMongoClient` behind the same `KnowledgeStore` protocol.

Search modes:
- `text`: `$search` compound (must/should) over title/body with a `kind` filter and an
  optional `facets.*`/`status` $match afterwards.
- `vector`: `$vectorSearch` with a `filter` restricted to the index's filter fields
  (kind, status, facets.language/framework/ecosystem/tool); anything else in `filters`
  is applied as a `$match` stage after.
- `hybrid`: native `$rankFusion` over a vector pipeline and a text pipeline (verified on
  MongoDB 8.0.32 by spike S1); falls back to manual RRF (`$unionWith`, k=60) on a
  server that rejects `$rankFusion` (e.g. `CommandNotFound`/`UnrecognizedCommand`, or
  an "$rankFusion" mention in the OperationFailure message).

Dedupe: before insert, `$vectorSearch` restricted to the same `kind` (index filter);
a top hit with cosine similarity >= 0.92 is merged into (`seen_count += 1`, `sources`
appended, `tags` unioned, `updated_at` refreshed) instead of inserting a new document.
`vectorSearchScore` for a cosine index is `(1 + cos) / 2` (S1); the threshold is
converted once, at module import, via `_cosine_to_vector_search_score`.

Documents are `KnowledgeItem.to_doc()` plus `embedding`; `embedding` is stripped from
every read path (search, get, list_items) so it never round-trips to a caller.
"""

from __future__ import annotations

from typing import Any, Literal

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import OperationFailure

from portpilot.core.interfaces import Embedder, NotFound
from portpilot.core.models import Hit, KnowledgeItem, KnowledgeKind, SearchMode, utcnow
from portpilot.knowledge.indexes import TEXT_INDEX_NAME, VECTOR_INDEX_NAME

DEDUPE_COSINE_THRESHOLD = 0.92
RRF_K = 60


def _cosine_to_vector_search_score(cosine: float) -> float:
    """S1: for a cosine-similarity index, `vectorSearchScore` is `(1 + cos) / 2`."""
    return (1.0 + cosine) / 2.0


DEDUPE_SCORE_THRESHOLD = _cosine_to_vector_search_score(DEDUPE_COSINE_THRESHOLD)

_VECTOR_FILTER_KEYS = {
    "kind",
    "status",
    "facets.language",
    "facets.framework",
    "facets.ecosystem",
    "facets.tool",
}


def _text_of(item: KnowledgeItem) -> str:
    return f"{item.title}\n{item.body}\n{' '.join(item.tags)}"


def _strip_embedding(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("embedding", None)
    doc.pop("_id", None)
    return doc


def _split_filters(filters: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a filters dict into (vector-index-eligible, everything else -> $match)."""
    filters = filters or {}
    indexed = {k: v for k, v in filters.items() if k in _VECTOR_FILTER_KEYS}
    rest = {k: v for k, v in filters.items() if k not in _VECTOR_FILTER_KEYS}
    return indexed, rest


class AtlasKnowledgeStore:
    """Implements `core.interfaces.KnowledgeStore` on collection `knowledge`."""

    def __init__(
        self,
        uri: str,
        db_name: str,
        embedder: Embedder,
        hybrid: Literal["rankfusion", "rrf"] = "rankfusion",
    ) -> None:
        self.client: MongoClient = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.db: Database = self.client[db_name]
        self.coll = self.db["knowledge"]
        self.embedder = embedder
        self.hybrid = hybrid

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------ upsert

    def upsert(self, item: KnowledgeItem, dedupe: bool = True) -> str:
        vector = self.embedder.embed([_text_of(item)], "document")[0]

        if dedupe:
            merged_id = self._merge_if_duplicate(item, vector)
            if merged_id is not None:
                return merged_id

        doc = item.to_doc()
        doc["embedding"] = vector
        doc["_id"] = item.id
        self.coll.replace_one({"_id": item.id}, doc, upsert=True)
        return item.id

    def _merge_if_duplicate(self, item: KnowledgeItem, vector: list[float]) -> str | None:
        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": VECTOR_INDEX_NAME,
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": 20,
                    "limit": 1,
                    "filter": {"kind": {"$eq": item.kind}},
                }
            },
            {"$project": {"_id": 1, "score": {"$meta": "vectorSearchScore"}}},
        ]
        try:
            top = next(iter(self.coll.aggregate(pipeline)), None)
        except OperationFailure:
            # Index not yet queryable (e.g. right after ensure_indexes on a fresh
            # collection) -- treat as "no duplicate found" rather than failing the write.
            return None
        if top is None or top["score"] < DEDUPE_SCORE_THRESHOLD:
            return None

        existing_id = top["_id"]
        update = {
            "$inc": {"seen_count": 1},
            "$addToSet": {"tags": {"$each": item.tags}},
            "$push": {"sources": {"$each": [s.to_doc() for s in item.sources]}},
            "$set": {"updated_at": utcnow()},
        }
        self.coll.update_one({"_id": existing_id}, update)
        return existing_id

    # -------------------------------------------------------------------- get

    def get(self, item_id: str) -> KnowledgeItem:
        doc = self.coll.find_one({"_id": item_id})
        if doc is None:
            raise NotFound(item_id)
        return KnowledgeItem.from_doc(_strip_embedding(doc))

    # ----------------------------------------------------------------- search

    def search(
        self,
        query: str,
        *,
        kinds: list[KnowledgeKind] | None = None,
        mode: SearchMode = "hybrid",
        filters: dict[str, Any] | None = None,
        limit: int = 8,
    ) -> list[Hit]:
        if mode == "text":
            return self._search_text(query, kinds, filters, limit)
        if mode == "vector":
            return self._search_vector(query, kinds, filters, limit)
        return self._search_hybrid(query, kinds, filters, limit)

    def _kind_match(self, kinds: list[KnowledgeKind] | None) -> dict[str, Any]:
        return {"kind": {"$in": list(kinds)}} if kinds else {}

    def _text_stage(self, query: str, kinds: list[KnowledgeKind] | None) -> dict[str, Any]:
        compound: dict[str, Any] = {"must": [{"text": {"query": query, "path": ["title", "body"]}}]}
        if kinds:
            # `kind` is mapped as a `token` field: filtering it needs `equals`
            # (token fields don't support the `text` operator), OR'd across kinds.
            compound["filter"] = [
                {
                    "compound": {
                        "should": [{"equals": {"value": k, "path": "kind"}} for k in kinds],
                        "minimumShouldMatch": 1,
                    }
                }
            ]
        return {"$search": {"index": TEXT_INDEX_NAME, "compound": compound}}

    def _vector_stage(
        self,
        qvector: list[float],
        kinds: list[KnowledgeKind] | None,
        indexed_filters: dict[str, Any],
        limit: int,
        num_candidates: int = 100,
    ) -> dict[str, Any]:
        vfilter: dict[str, Any] = {k: {"$eq": v} for k, v in indexed_filters.items()}
        if kinds:
            vfilter["kind"] = {"$in": list(kinds)}
        stage: dict[str, Any] = {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": qvector,
                "numCandidates": num_candidates,
                "limit": limit,
            }
        }
        if vfilter:
            stage["$vectorSearch"]["filter"] = vfilter
        return stage

    def _search_text(
        self,
        query: str,
        kinds: list[KnowledgeKind] | None,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[Hit]:
        _, rest = _split_filters(filters)
        pipeline: list[dict[str, Any]] = [
            self._text_stage(query, kinds),
            {"$limit": limit},
            {"$addFields": {"score": {"$meta": "searchScore"}}},
        ]
        if rest:
            pipeline.append({"$match": rest})
        docs = list(self.coll.aggregate(pipeline))
        return [
            Hit(KnowledgeItem.from_doc(_strip_embedding(d)), float(d.get("score", 0.0)), "text")
            for d in docs
        ]

    def _search_vector(
        self,
        query: str,
        kinds: list[KnowledgeKind] | None,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[Hit]:
        qvector = self.embedder.embed([query], "query")[0]
        indexed, rest = _split_filters(filters)
        pipeline: list[dict[str, Any]] = [
            self._vector_stage(qvector, kinds, indexed, limit),
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        ]
        if rest:
            pipeline.append({"$match": rest})
        docs = list(self.coll.aggregate(pipeline))
        return [
            Hit(KnowledgeItem.from_doc(_strip_embedding(d)), float(d.get("score", 0.0)), "vector")
            for d in docs
        ]

    def _search_hybrid(
        self,
        query: str,
        kinds: list[KnowledgeKind] | None,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[Hit]:
        qvector = self.embedder.embed([query], "query")[0]
        indexed, rest = _split_filters(filters)

        if self.hybrid == "rankfusion":
            try:
                return self._hybrid_rankfusion(query, qvector, kinds, indexed, rest, limit)
            except OperationFailure as exc:
                if "rankFusion" not in str(exc) and "PlanExecutor" not in str(exc):
                    raise
                # Server doesn't understand $rankFusion (e.g. < 8.0's aggregation
                # engine) -- fall back to manual RRF, per S1's documented fallback.
        return self._hybrid_manual_rrf(query, qvector, kinds, indexed, rest, limit)

    def _hybrid_rankfusion(
        self,
        query: str,
        qvector: list[float],
        kinds: list[KnowledgeKind] | None,
        indexed_filters: dict[str, Any],
        rest_filters: dict[str, Any],
        limit: int,
    ) -> list[Hit]:
        vector_pipeline = [self._vector_stage(qvector, kinds, indexed_filters, limit)]
        text_pipeline = [self._text_stage(query, kinds), {"$limit": limit}]
        pipeline: list[dict[str, Any]] = [
            {
                "$rankFusion": {
                    "input": {
                        "pipelines": {
                            "vectorPipeline": vector_pipeline,
                            "textPipeline": text_pipeline,
                        }
                    },
                    "combination": {"weights": {"vectorPipeline": 0.6, "textPipeline": 0.4}},
                    "scoreDetails": True,
                }
            },
            {"$limit": limit},
            {
                "$addFields": {
                    "score": {"$meta": "score"},
                    "scoreDetails": {"$meta": "scoreDetails"},
                }
            },
        ]
        if rest_filters:
            pipeline.append({"$match": rest_filters})
        docs = list(self.coll.aggregate(pipeline))
        return [self._hit_from_rankfusion_doc(d) for d in docs]

    def _hit_from_rankfusion_doc(self, doc: dict[str, Any]) -> Hit:
        details = doc.pop("scoreDetails", None) or {}
        via = self._via_from_score_details(details)
        return Hit(KnowledgeItem.from_doc(_strip_embedding(doc)), float(doc.get("score", 0.0)), via)

    @staticmethod
    def _via_from_score_details(details: dict[str, Any]) -> Literal["vector", "text", "both"]:
        sub = details.get("details") or details.get("value", {}).get("details") or []
        names = {d.get("inputPipelineName") for d in sub if isinstance(d, dict)}
        names = {n for n in names if n}
        has_vector = "vectorPipeline" in names
        has_text = "textPipeline" in names
        if has_vector and has_text:
            return "both"
        if has_vector:
            return "vector"
        return "text"

    def _hybrid_manual_rrf(
        self,
        query: str,
        qvector: list[float],
        kinds: list[KnowledgeKind] | None,
        indexed_filters: dict[str, Any],
        rest_filters: dict[str, Any],
        limit: int,
    ) -> list[Hit]:
        vector_branch: list[dict[str, Any]] = [
            self._vector_stage(qvector, kinds, indexed_filters, limit),
            {"$group": {"_id": None, "docs": {"$push": "$$ROOT"}}},
            {"$unwind": {"path": "$docs", "includeArrayIndex": "rank"}},
            {
                "$project": {
                    "_id": "$docs._id",
                    "doc": "$docs",
                    "rrf_vec": {"$divide": [1.0, {"$add": [RRF_K, "$rank", 1]}]},
                }
            },
        ]
        text_branch: list[dict[str, Any]] = [
            self._text_stage(query, kinds),
            {"$limit": limit},
            {"$group": {"_id": None, "docs": {"$push": "$$ROOT"}}},
            {"$unwind": {"path": "$docs", "includeArrayIndex": "rank"}},
            {
                "$project": {
                    "_id": "$docs._id",
                    "doc": "$docs",
                    "rrf_text": {"$divide": [1.0, {"$add": [RRF_K, "$rank", 1]}]},
                }
            },
        ]
        pipeline: list[dict[str, Any]] = [
            *vector_branch,
            {"$unionWith": {"coll": self.coll.name, "pipeline": text_branch}},
            {
                "$group": {
                    "_id": "$_id",
                    "doc": {"$first": "$doc"},
                    "rrf_vec": {"$sum": {"$ifNull": ["$rrf_vec", 0]}},
                    "rrf_text": {"$sum": {"$ifNull": ["$rrf_text", 0]}},
                }
            },
            {"$addFields": {"score": {"$add": ["$rrf_vec", "$rrf_text"]}}},
            {"$sort": {"score": -1}},
            {"$limit": limit},
        ]
        if rest_filters:
            pipeline.append({"$match": {f"doc.{k}": v for k, v in rest_filters.items()}})
        docs = list(self.coll.aggregate(pipeline))
        hits = []
        for d in docs:
            via: Literal["vector", "text", "both"]
            has_vec, has_text = d.get("rrf_vec", 0) > 0, d.get("rrf_text", 0) > 0
            via = "both" if has_vec and has_text else ("vector" if has_vec else "text")
            hits.append(
                Hit(KnowledgeItem.from_doc(_strip_embedding(d["doc"])), float(d["score"]), via)
            )
        return hits

    # ------------------------------------------------------------- list/status

    def list_items(
        self, kinds: list[KnowledgeKind] | None = None, run_id: str | None = None, limit: int = 100
    ) -> list[KnowledgeItem]:
        match: dict[str, Any] = {}
        if kinds:
            match["kind"] = {"$in": list(kinds)}
        if run_id:
            match["sources.run_id"] = run_id
        cursor = self.coll.find(match).sort("updated_at", -1).limit(limit)
        return [KnowledgeItem.from_doc(_strip_embedding(d)) for d in cursor]

    def set_status(self, item_id: str, status: str) -> None:
        result = self.coll.update_one(
            {"_id": item_id}, {"$set": {"status": status, "updated_at": utcnow()}}
        )
        if result.matched_count == 0:
            raise NotFound(item_id)
