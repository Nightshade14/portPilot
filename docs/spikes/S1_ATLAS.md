# Spike S1: Atlas search, vector search and embeddings

Cluster: real Atlas M0, MongoDB **8.0.32**. Local: `mongodb/mongodb-atlas-local:latest` (mongod **8.3.11**). All work in `spikes/s1/`; database `portpilot_spike` was created and dropped, never left populated; zero search indexes remain cluster-wide.

## Decision table

| Question | Decision |
|---|---|
| Hybrid method | **Use native `$rankFusion`** over `$vectorSearch` + `$search` pipelines. It IS accepted on 8.0.32 — verified on the real cluster, not just docs. Keep the manual RRF (`$vectorSearch` + `$unionWith($search)`, k=60) implemented in `spikes/s1/hybrid.py` as a fallback for any deployment that turns out not to support it, but MVP_PLAN's "S1 checks whether it also accepts `$vectorSearch`/`$search` on 8.0" is answered: **yes**. |
| `knowledge_text` index (verbatim) | See below |
| `knowledge_vec` index (verbatim) | See below |
| Embedding model + dimension | `voyage-4`, default `output_dimension` = **1024** (also supports 256/512/2048) |
| `autoEmbed` — yes or no | **Yes, it works on Atlas M0.** Contradicts the docs page structure (which only documents an explicit Atlas creation flow under a "Self-Managed" heading and describes availability as MongoDB Community 8.2+ / Docker / Kubernetes Operator) — empirically the index type is accepted, builds, and reaches `status: READY, queryable: true` on the real M0 cluster in ~seconds. Trust the empirical result over the docs' apparent scoping; MVP_PLAN can use `autoEmbed` if wanted, but see gotcha below about not yet verifying live query-time embedding generation (no Voyage key). |
| atlas-local tag + run command | `mongodb/mongodb-atlas-local:latest` (resolves to mongod 8.3.11). `docker run -d --name pp-test-s1-atlaslocal -p 127.0.0.1:27019:27017 mongodb/mongodb-atlas-local:latest`. Connection string: `mongodb://127.0.0.1:27019/?directConnection=true`. |

### `knowledge_text` (verbatim, as created and verified queryable)

```json
{
  "name": "knowledge_text",
  "type": "search",
  "definition": {
    "mappings": {
      "dynamic": false,
      "fields": {
        "title": { "type": "string", "analyzer": "lucene.standard" },
        "body": { "type": "string", "analyzer": "lucene.standard" },
        "tags": { "type": "token" }
      }
    }
  }
}
```

### `knowledge_vec` (verbatim, as created and verified queryable)

```json
{
  "name": "knowledge_vec",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
      { "type": "filter", "path": "kind" },
      { "type": "filter", "path": "status" },
      { "type": "filter", "path": "facets.language" }
    ]
  }
}
```

## Goal 1 — Indexes on the real cluster

Ran `spikes/s1/indexes.py` against `portpilot_spike.knowledge_spike` on the real M0 cluster.

- Pre-flight: scanned every non-system database/collection on the cluster — **zero pre-existing search indexes anywhere**, confirming the cluster starts clean at the 3-index M0 limit.
- Created both `knowledge_text` (type `search`) and `knowledge_vec` (type `vectorSearch`) via one `create_search_indexes([...])` call with `SearchIndexModel`.
- Polled `list_search_indexes()` every 5s. **Both became `queryable: true` after ~42s** (41.9s and 42.6s across two runs).
- Collection dropped in a `finally` block. **Verified zero search indexes remain** after the drop, both via `list_search_indexes()` on the (now-recreated-on-demand, then-redropped) collection and by leaving the `portpilot_spike` database with zero collections.
- The M0 3-index limit was never hit (2 of 3 slots used, then freed).

## Goal 2 — Queries

Inserted 12 fixture docs (`spikes/s1/query_tests.py::build_fixture_docs`) across kinds `lesson`, `gotcha`, `tool_card`, with two intentional paraphrase pairs sharing the same hash seed (so their embeddings are identical/near-identical by construction — a stronger test than "nearby," but exercises the same fan-out/grouping code paths). Embeddings are deterministic hash-seeded unit vectors (`hash_seeded_unit_vector`, SHA-256-derived, no external embedding call).

- **`$search` text query** for `"retry backoff"` → correctly returned "Retry on 429 with exponential backoff" (score 4.08).
- **`$vectorSearch` with `kind` filter** (`kind: "gotcha"`) → top 5 results all `kind: "gotcha"`, ranked by cosine similarity to the query vector; the two seeded-identical paraphrase docs both scored 1.0 as expected.
- **`$rankFusion` over `$vectorSearch` + `$search`** (weights vector=0.6, text=0.4): **accepted and executed successfully on 8.0.32.** Returned blended/reciprocal-rank-style scores merging both branches. `rank_fusion_supported = True` on both the real Atlas cluster and the local `atlas-local:latest` (mongod 8.3.11) instance.
- **Manual RRF fallback** (`$vectorSearch` + `$unionWith($search)`, `$group`, k=60 reciprocal-rank scoring): implemented and verified in `spikes/s1/hybrid.py` / exercised by `query_tests.py`. Produces a sane top-5 ranked by summed reciprocal rank across both branches. Works identically on both the real cluster and atlas-local.

**Determination for MVP_PLAN:** `$rankFusion` does accept `$vectorSearch` and `$search` as input pipelines on MongoDB 8.0.32. The plan's assumption that this needed checking is resolved in the affirmative — no fallback to manual RRF is required for correctness on this server version, though the manual implementation stays available as a defensive fallback.

## Goal 3 — Voyage embeddings (UNVERIFIED — no live key)

From the Atlas Embedding and Reranking API docs (`https://www.mongodb.com/docs/api/doc/atlas-embedding-and-reranking-api/operation/operation-createembedding`) and Voyage AI docs (`https://www.mongodb.com/docs/voyageai/`):

- **Endpoint:** `POST https://ai.mongodb.com/v1/embeddings`
- **Auth header:** `Authorization: Bearer <model-api-key>` (key created in Atlas UI: AI Model APIs → Create model API key)
- **Request body:**
  ```json
  {
    "input": "string or array of strings (max 1000 items)",
    "model": "voyage-4",
    "input_type": "query" | "document" | null,
    "truncation": true,
    "output_dimension": 1024,
    "output_dtype": "float",
    "encoding_format": null
  }
  ```
- **`input_type`:** `document` when storing (prepends a document-retrieval prompt), `query` when searching (prepends a query-retrieval prompt); omit for a generic embedding. Confirms MVP_PLAN's assumption.
- **Response (200):** `{"object": "list", "data": [{"object": "embedding", "embedding": [...], "index": 0}, ...], "model": "...", "usage": {"total_tokens": N}}`
- **`voyage-4` default `output_dimension`:** **1024** (confirmed both in the API spec and the quickstart's live example output). Allowed values: `256`, `512`, `1024`, `2048`.
- **Batch limits:** up to **1000 input strings** per request; max total tokens per request for `voyage-4` is **320,000** (per the API spec's per-model token caps: 1M for `-lite` variants, 320K for `voyage-3.5`/`voyage-4`/`voyage-code-4`/`voyage-2`, 120K for the `-large`/`code-3`/`finance-2`/`law-2` variants).
- **Rate limits (Usage Tier 1, default):** `voyage-4` = **8,000,000 TPM / 2,000 RPM**. Exceeding either returns HTTP 429.
- **Error codes:** 400 (invalid request/oversized batch/token overflow), 401 (bad/missing bearer token), 403 (IP not allowed), 429 (rate limit), 500/502/503/504 (retry-worthy server errors).

`spikes/s1/voyage_client.py` implements `embed()` with httpx, retrying on 429 and 5xx with exponential backoff (`base_backoff_s * 2**attempt`, default 5 retries), raising `VoyageEmbeddingError` on 400/401/403 or exhausted retries. **The live call is UNVERIFIED** — `VOYAGE_API_KEY` is not set in `.env`.

One-line command to verify once a key exists:

```bash
uv run python -c "from dotenv import dotenv_values; from spikes.s1.voyage_client import embed; k=dotenv_values('/Users/satyamchatrola/codes/personal/portPilot/.env')['VOYAGE_API_KEY']; print(len(embed(['hello world'], api_key=k, input_type='document')[0]))"
```//expected output: 1024

## Goal 4 — Automated Embedding (`autoEmbed`)

**Docs read first, then empirically tested — the docs and the live cluster disagree, and the live cluster wins.**

The "Automated Embedding Overview" page (`https://www.mongodb.com/docs/vector-search/crud-embeddings/automated-embedding`) has separate "Atlas" and "Self-Managed" tab content; the visible "Enable and Use Automated Embedding" walkthrough for creating an `autoEmbed` index (with a bare `"fields": [{"type": "autoEmbed", ...}]` definition, no separate API-key-at-deployment step) reads as the Atlas-native path, while a second, more detailed walkthrough further down is explicitly for self-managed `mongot` deployments requiring API keys supplied at MongoDB Community initialization. The page does **not** state an M0-specific restriction.

Rather than rely on that ambiguous reading, I created one directly on the real M0 cluster:

```json
{
  "name": "knowledge_autoembed",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      { "type": "autoEmbed", "modality": "text", "path": "body", "model": "voyage-4" }
    ]
  }
}
```

Result: **accepted immediately, and reached `status: READY, queryable: true` on all 3 shard hosts within seconds.** The materialized definition MongoDB stored back shows it auto-filled `numDimensions: 1024, similarity: cosine, quantization: scalar` — matching the `voyage-4` default dimension from goal 3.

**`autoEmbed` works on Atlas M0** (at least for index creation/build — the actual embedding-generation step at insert/query time was not exercised because `VOYAGE_API_KEY` is not set in this environment, so whether an M0 cluster with no project-level Voyage key configured would successfully generate real embeddings from live data is UNVERIFIED; the index structure itself is real and queryable).

## Goal 5 — Local development image

- **Working tag:** `mongodb/mongodb-atlas-local:latest` → resolves to mongod **8.3.11** on this arm64 / kernel 6.19+ Docker VM. Started without the `mongo:8.0` kernel-incompatibility crash.
- **Time to ready:** mongod itself answered `{ok: 1}` to `ping` in **under 1 second** after container start (image was already pulled once; a cold pull adds image-download time, observed ~15s for the multi-layer `latest` image). The bundled `mongot` (search/vector) component took **~2 seconds** for both search indexes to reach `queryable: true` on a freshly inserted 12-doc collection — much faster than the real Atlas M0's ~42s.
- **Connection string:** `mongodb://127.0.0.1:27019/?directConnection=true` — **`directConnection=true` is required**; without it the driver's replica-set/topology discovery behaves unexpectedly against the single-node local container.
- **Container:** ran as `pp-test-s1-atlaslocal` on `127.0.0.1:27019`, removed (`docker rm -f`) at the end of the run. No other container on the host was touched.
- **Reran goals 1 and 2 against it:** both indexes created and verified queryable (~2s), `$search`, `$vectorSearch` with filter, native `$rankFusion`, and manual RRF fallback all produced the same shape of correct results as on the real cluster. `rank_fusion_supported_locally = True` on mongod 8.3.11 as well.

## Every exact error message hit

1. **`create_search_indexes` on a not-yet-existent collection:**
   ```
   pymongo.errors.OperationFailure: Collection 'portpilot_spike.knowledge_spike' does not exist., full error: {'ok': 0.0, 'errmsg': "Collection 'portpilot_spike.knowledge_spike' does not exist.", 'code': 26, 'codeName': 'NamespaceNotFound', ...}
   ```
   **Gotcha:** Atlas Search/Vector Search indexes cannot be created on a collection that hasn't been materialized yet (no documents, no explicit `create_collection`). Fix: `db.create_collection(name)` (or insert at least one document) before `create_search_indexes`.

No other errors were hit during this spike — `$rankFusion`, `autoEmbed`, and the `atlas-local:latest` tag all worked on the first real attempt after the collection-existence fix above. This is notable: MVP_PLAN's hedges around "S1 checks whether $rankFusion accepts $vectorSearch/$search on 8.0" and "use autoEmbed only if S1 shows it works on our cluster tier" both resolve to "it works," which is a more permissive result than the plan assumed going in.

## Gotchas (non-error)

- **M0's 3-search-index-per-cluster limit is cluster-wide, not per-collection or per-database.** Verified by scanning every database/collection on the cluster before starting — always do this before creating indexes on a shared M0, and always drop in a `finally`.
- **`list_search_indexes()` polling needs a real interval** — indexes are not instantaneously queryable even after the create call returns 2xx; on real Atlas M0 the wait was consistently ~42s for two indexes together, versus ~2s on local atlas-local. Budget for the slower real-cluster latency in any code depending on index readiness (e.g. STP tool-selection gates).
- **`autoEmbed`'s materialized definition differs from what you submit** — it silently fills in `numDimensions`, `similarity`, and `quantization` defaults matching the chosen model; don't assume the stored definition is byte-identical to the one you sent.
- **Paraphrase-pair fixture design note:** using the *same* hash seed for a "paraphrase pair" produces identical (not merely nearby) vectors. That's fine for exercising the ranking/filter code paths in this spike, but a real embedding-quality test would need genuinely distinct-but-semantically-close vectors (i.e., real Voyage embeddings of actual paraphrases) — deferred to whenever `VOYAGE_API_KEY` exists.

## What could not be verified

- **Live Voyage embedding calls** (`spikes/s1/voyage_client.py`) — no `VOYAGE_API_KEY` in `.env`. Marked UNVERIFIED; one-line verification command given above.
- **`autoEmbed`'s actual embedding generation on real inserted/queried text** on M0 without a project-level Voyage key configured in Atlas — the index structure was verified `READY`/`queryable`, but no document was inserted against it and no `$vectorSearch` with `query.text` was run, since that would require a working Voyage API key wired into the Atlas project (a UI-side step, not something `.env` or pymongo can provide).
- Whether the Atlas-tab "Enable and Use Automated Embedding" walkthrough is officially GA-supported on M0 specifically (docs don't say either way) — only that it functionally works, per direct test.

## Commit

Committed on `spike/s1`.
