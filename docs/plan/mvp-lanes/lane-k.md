# Lane K: Knowledge and retrieval

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-k`, on branch `mvp/k`.
- **Wave:** 1.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` §3.10;
  - `src/portpilot/core/{models,interfaces,fakes,config}.py`, which are frozen;
  - `docs/spikes/S1_ATLAS.md` and `spikes/s1/*.py`, where the index definitions and the hybrid search pipelines are already verified.

## Owns

- `src/portpilot/knowledge/` (new package).
- `tests/knowledge/`.

## Facts established by the spikes

- **Voyage:** `POST https://api.voyageai.com/v1/embeddings` with `Authorization: Bearer <VOYAGE_API_KEY>` and body `{"input": [...], "model": "voyage-4", "input_type": "document"|"query"}`. The response carries `data[].embedding` (1024 dims) and `usage.total_tokens`.
  - The user's key is a direct Voyage key. It gets a 403 from `ai.mongodb.com`.
  - The base URL comes from `settings.voyage_base_url`.
- **Hybrid search:** native `$rankFusion` over `$vectorSearch` and `$search` works on the real cluster (8.0.32). The manual RRF fallback (`$unionWith`) is in `spikes/s1/hybrid.py`.
- **Index budget:** the M0 cluster allows only 3 search indexes in total. Production uses exactly 2, `knowledge_text` and `knowledge_vec`, on `<MVP_MONGODB_DB>.knowledge`.
- **Local testing:** `mongodb/mongodb-atlas-local:latest` (8.3.11) starts on this machine. Connect with `mongodb://127.0.0.1:27019/?directConnection=true`. Index builds there take about 2 s.
- **Vector scores:** for cosine similarity, `vectorSearchScore` is `(1 + cos) / 2`. Convert it before comparing against a cosine threshold.

## Build

1. **`embedder.py`:** `VoyageEmbedder(api_key, base_url, model="voyage-4", dims=1024)`.
   - It implements `core.interfaces.Embedder` with httpx.
   - Batch according to the documented limits in S1.
   - Retry 429 and 5xx with backoff.
   - Error messages must never contain the key.
   - Also add `make_embedder(settings)`, which falls back to `core.fakes.FakeEmbedder` when there is no key and `settings.store_backend == "memory"`.
2. **`indexes.py`:**
   - The `knowledge_text` definition from S1 (title/body `lucene.standard`, tags `token`), plus `kind` as `token` so text search can filter.
   - The `knowledge_vec` definition: path `embedding`, the dims parameter, cosine, and filter fields `kind`, `status`, `facets.language`, `facets.framework`, `facets.ecosystem`, `facets.tool`.
   - `ensure_indexes(db, dims, wait=True, timeout_s=180)`: idempotent. It creates missing indexes, updates a changed definition, and polls until queryable.
3. **`store.py`:** `AtlasKnowledgeStore(uri, db_name, embedder, hybrid="rankfusion"|"rrf")`.
   - It implements `KnowledgeStore` on collection `knowledge`.
   - The embedding covers `title + body + tags`.
   - **Dedupe:** a `$vectorSearch` restricted to the same `kind`. A top hit with cosine ≥ 0.92 is merged into: `seen_count += 1`, sources appended, tags unioned, `updated_at` set.
   - **Search modes:** `text` (`$search` compound with a filter on `kind`), `vector` (`$vectorSearch` with a filter), and `hybrid`.
   - `filters` map to the index filter fields. Anything else is applied as a `$match` afterwards.
   - Documents are `KnowledgeItem.to_doc()` plus `embedding`. Never return the embedding.
   - Use the sync-over-async loop-thread pattern from v0 `store/atlas.py`, or plain sync `MongoClient` if simpler. Document the choice.
4. **`render.py`:** `render_markdown(items, kind) -> str` produces `LESSONS.md`, `GOTCHAS.md` and `MEMORY.md`. Show title, body, tags, `seen_count` and sources, newest first.
5. **`cli.py`:** a Typer sub-app `knowledge_app` with:
   - `init-indexes`: uses `load_mvp_settings()`;
   - `search QUERY --kind --mode --limit`;
   - `add --kind --title --body --tag`.

   The Lead wires it into `portpilot` later. Don't edit `src/portpilot/cli.py`.

## Tests

- **Unit tests** (no marker): embedder batching and retry, using `httpx.MockTransport`; the dedupe threshold conversion; the markdown renderer.
- **`atlas_local` tests:**
  - Start `pp-test-k-atlaslocal` from `mongodb/mongodb-atlas-local:latest` on `127.0.0.1:27019` yourself. Keep it running between test runs, and remove it when the lane is done.
  - Use `PORTPILOT_TEST_ATLAS_LOCAL_URI`, and `FakeEmbedder(dims=64)` with indexes built for 64 dims.
  - An exact-keyword query finds its item in `text` mode.
  - A query sharing words finds it in `vector` mode.
  - `hybrid` returns the union, ranked, with `via="both"` when an item is found both ways.
  - Kind and facet filters apply.
  - Dedupe merges.
  - `ensure_indexes` is idempotent.
- **`live_atlas` + `live_voyage`, manual:** one test against the real cluster db `portpilot_mvp` with the real `VoyageEmbedder`.
  - It must first check `list_search_indexes` on the target collection and never create more than the 2 production indexes.
  - Its items carry `status="test"`, and it deletes them afterwards.
  - Run it once and report the result. Don't leave test documents behind.

## Done

- The unit tests and `PORTPILOT_TEST_ATLAS_LOCAL_URI=mongodb://127.0.0.1:27019/?directConnection=true uv run pytest tests/knowledge -m "not live_atlas"` are green.
- The live test has passed once.
- Ruff is clean.
- Everything is committed on `mvp/k`.

## Stop conditions

- **Index limit:** if the index limit is hit on the real cluster, stop and report the index names.
- **Interface change:** stop and report it; don't edit `core/`.
- **Time box:** about 2.5 hours.
