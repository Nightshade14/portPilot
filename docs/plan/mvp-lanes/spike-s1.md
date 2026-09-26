# Spike S1: Atlas search, vector search and embeddings

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-spike-s1`, on branch `spike/s1`.
- **Read first:** `docs/plan/MVP_PLAN.md` sections 3.10 and 4, and the S1 bullet in section 7.
- **Where your work goes:**
  - probe code in `spikes/s1/`;
  - findings in `docs/spikes/S1_ATLAS.md`.
- **Don't touch:** `src/` or `tests/`.

**Secrets:**
- `MONGODB_URI` in `.env` points at the real Atlas M0 cluster, which runs MongoDB 8.0.32.
- `VOYAGE_API_KEY` is not set yet.

## Goals

Record the exact commands, results and error messages for each goal.

### 1. Indexes on the real cluster

Work in database `portpilot_spike`, collection `knowledge_spike`.

1. Using pymongo `create_search_index(SearchIndexModel(..., type=...))`, create:
   - an Atlas Search index `knowledge_text`: `title` and `body` with the standard analyzer, and `tags` as token/keyword;
   - a vector index `knowledge_vec`: type `vectorSearch`, path `embedding`, 1024 dimensions, cosine similarity, with filter fields `kind`, `status` and `facets.language`.
2. Poll `list_search_indexes()` until both are queryable, and record how long that took.

M0 allows only 3 search indexes per cluster:
- Always drop the collection in a `finally` block.
- Verify afterwards that no search index remains.
- Never touch any other database.

If index creation is refused because of the limit:
- stop;
- list the existing search index names only;
- report.

### 2. Queries

Insert about 12 documents (kinds `lesson`, `gotcha` and `tool_card`) with deterministic fake embeddings. Use hash-seeded unit vectors, and make 2 paraphrase documents share nearby vectors.

Test:
- a `$search` text query;
- a `$vectorSearch` query with a `kind` filter;
- a hybrid `$rankFusion` over a `$vectorSearch` pipeline and a `$search` pipeline, with weights.

Determine precisely whether `$rankFusion` accepts `$vectorSearch` and `$search` inputs on 8.0.32.

Implement and verify the fallback: manual reciprocal-rank fusion (k=60), using `$vectorSearch` plus `$unionWith` a `$search` pipeline, then `$group` and score arithmetic. Put both approaches in `spikes/s1/hybrid.py` as functions.

### 3. Voyage embeddings

From the official docs (https://www.mongodb.com/docs/voyageai/ ; append `.md` to a page URL to get markdown), find:
- the exact request and response format of `POST https://ai.mongodb.com/v1/embeddings`;
- the auth header;
- `input_type` (`document` / `query`);
- the default and allowed `output_dimension` for `voyage-4`;
- batch limits and rate limits.

Write `spikes/s1/voyage_client.py` with httpx, retrying on 429 and 5xx. The live call can't be made without a key: mark it UNVERIFIED, and give a one-line command the user can run once the key exists.

### 4. Automated Embedding

Determine from the docs whether `autoEmbed` vector indexes work on M0 (free) clusters.

If the docs don't settle it:
1. Try creating one on `knowledge_spike` (text field `body`, model `voyage-4`).
2. Record the exact error.
3. Drop it.

### 5. Local development image

Find a `mongodb/mongodb-atlas-local` image tag that starts on this Docker VM.
- The VM is arm64 with kernel 6.19 or newer.
- `mongo:8.0` refused to start there with "Linux kernel versions 6.19 and newer has a known incompatibility".

Steps:
1. Try tags newest first, for example `latest`, `8.2`, `8.0`, checking with `docker manifest inspect` or `docker pull`.
2. Run it as container `pp-test-s1-atlaslocal` on `127.0.0.1:27019`.
3. Record:
   - the working tag;
   - how long it takes to become ready;
   - the connection string (it probably needs `directConnection=true`).
4. Rerun goals 1 and 2 against it.
5. Remove the container at the end.

## Deliverable

`docs/spikes/S1_ATLAS.md` must contain:
- **A decision table covering:**
  - which hybrid method to use;
  - both index definitions as verbatim JSON;
  - the embedding model and dimension;
  - `autoEmbed` yes or no;
  - the atlas-local tag and its run command.
- **Every exact error message you hit, and gotchas.**

Commit on `spike/s1`.

## Stop conditions

- **Done:** all 5 goals are answered. The live Voyage call may stay UNVERIFIED.
- **Time box:** about 60 minutes.
