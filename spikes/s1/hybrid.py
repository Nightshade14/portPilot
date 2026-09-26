"""Spike S1 goal 2: hybrid search approaches.

Both functions assume a collection with:
- an Atlas Search index named "knowledge_text" over title/body/tags
- a vectorSearch index named "knowledge_vec" over `embedding` (1024-dim, cosine)
  with filter fields kind, status, facets.language.
"""

from __future__ import annotations


def rank_fusion_pipeline(
    query_text: str,
    query_vector: list[float],
    *,
    kind_filter: str | None = None,
    vector_weight: float = 0.6,
    text_weight: float = 0.4,
    limit: int = 10,
    num_candidates: int = 100,
) -> list[dict]:
    """Native $rankFusion over a $vectorSearch pipeline and a $search pipeline.

    Empirically confirmed on this cluster (MongoDB 8.0.32): $rankFusion DOES
    accept $vectorSearch and $search as input pipelines. See
    docs/spikes/S1_ATLAS.md for the verification run and raw result.
    """
    vector_stage: dict = {
        "$vectorSearch": {
            "index": "knowledge_vec",
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": num_candidates,
            "limit": limit,
        }
    }
    if kind_filter:
        vector_stage["$vectorSearch"]["filter"] = {"kind": {"$eq": kind_filter}}

    search_stage: dict = {
        "$search": {
            "index": "knowledge_text",
            "text": {"query": query_text, "path": ["title", "body"]},
        }
    }

    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "vectorPipeline": [vector_stage],
                        "textPipeline": [search_stage, {"$limit": limit}],
                    }
                },
                "combination": {
                    "weights": {"vectorPipeline": vector_weight, "textPipeline": text_weight}
                },
                "scoreDetails": True,
            }
        },
        {"$limit": limit},
        {
            "$project": {
                "title": 1,
                "kind": 1,
                "score": {"$meta": "score"},
            }
        },
    ]


def manual_rrf_pipeline(
    query_text: str,
    query_vector: list[float],
    *,
    kind_filter: str | None = None,
    k: int = 60,
    limit: int = 10,
    num_candidates: int = 100,
) -> list[dict]:
    """Manual reciprocal-rank fusion via $vectorSearch + $unionWith($search), works on any version.

    RRF score per branch: 1 / (k + rank), rank is 1-based. Final score = sum
    over branches where the doc appeared (0 if it didn't appear in a branch).
    """
    vector_stage: dict = {
        "$vectorSearch": {
            "index": "knowledge_vec",
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": num_candidates,
            "limit": limit,
        }
    }
    if kind_filter:
        vector_stage["$vectorSearch"]["filter"] = {"kind": {"$eq": kind_filter}}

    vector_branch = [
        vector_stage,
        {"$group": {"_id": None, "docs": {"$push": "$$ROOT"}}},
        {"$unwind": {"path": "$docs", "includeArrayIndex": "rank"}},
        {
            "$project": {
                "_id": "$docs._id",
                "title": "$docs.title",
                "kind": "$docs.kind",
                "rrf_vec": {"$divide": [1.0, {"$add": [k, "$rank", 1]}]},
            }
        },
    ]

    text_branch = [
        {
            "$search": {
                "index": "knowledge_text",
                "text": {"query": query_text, "path": ["title", "body"]},
            }
        },
        {"$limit": limit},
        {"$group": {"_id": None, "docs": {"$push": "$$ROOT"}}},
        {"$unwind": {"path": "$docs", "includeArrayIndex": "rank"}},
        {
            "$project": {
                "_id": "$docs._id",
                "title": "$docs.title",
                "kind": "$docs.kind",
                "rrf_text": {"$divide": [1.0, {"$add": [k, "$rank", 1]}]},
            }
        },
    ]

    return [
        *vector_branch,
        {
            "$unionWith": {
                "coll": None,  # placeholder; caller must set to the source collection name
                "pipeline": text_branch,
            }
        },
        {
            "$group": {
                "_id": "$_id",
                "title": {"$first": "$title"},
                "kind": {"$first": "$kind"},
                "rrf_vec": {"$sum": {"$ifNull": ["$rrf_vec", 0]}},
                "rrf_text": {"$sum": {"$ifNull": ["$rrf_text", 0]}},
            }
        },
        {"$addFields": {"score": {"$add": ["$rrf_vec", "$rrf_text"]}}},
        {"$sort": {"score": -1}},
        {"$limit": limit},
        {"$project": {"title": 1, "kind": 1, "score": 1}},
    ]


def build_manual_rrf_pipeline_for(coll_name: str, *args, **kwargs) -> list[dict]:
    """Convenience wrapper that fills in $unionWith.coll (pymongo needs the literal name)."""
    pipeline = manual_rrf_pipeline(*args, **kwargs)
    for stage in pipeline:
        if "$unionWith" in stage:
            stage["$unionWith"]["coll"] = coll_name
    return pipeline
