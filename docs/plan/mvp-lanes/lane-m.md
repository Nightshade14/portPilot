# Lane M: Mongo state

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-m`, on branch `mvp/m`.
- **Wave:** 1.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` sections 3.7 and 4;
  - `src/portpilot/core/{models,interfaces,fakes}.py`, which are frozen;
  - `docs/spikes/S2_STRANDS.md` §5 and `spikes/s2/atlas_session_repository.py`;
  - v0's `src/portpilot/store/atlas.py`, which shows the async-client pattern to reuse.

## Owns

- `src/portpilot/store/v2/` (new package).
- `tests/store_v2/`.

You may only read everything else. `core/fakes.py` is the reference behavior: if it disagrees with the interface docstrings, report it and don't edit it.

## Build

1. **Shared loop helper:** `store/v2/_loop.py` holds the private event loop on a daemon thread. Copy v0's `_LoopThread` together with its task-cancelling `stop()`.
2. **`AtlasRunStore(uri, db_name)`:**
   - It implements `core.interfaces.RunStore` over `AsyncMongoClient` (`tz_aware=True`, `tzinfo=UTC`).
   - Collections: `migration_runs`, `plans`, `steps`, `events`, `artifacts`.
   - **Indexes** (create them in `init()`):
     - `migration_runs`: `run_id` unique, and `(status, lease.expires_at)`;
     - `plans`: `(run_id, version)` unique;
     - `steps`: `step_id` unique and `(run_id, seq)` unique;
     - `events`: `(run_id, seq)` unique;
     - `artifacts`: `artifact_id` unique and `(run_id, kind)`;
     - a TTL index on `expire_at` for both `events` and `artifacts`.
   - **`claim_run`:** a single atomic `find_one_and_update`. It matches `status == "queued"`, OR (`status == "running"` AND (`lease` null OR `lease.expires_at < now`)). It sorts by `created_at` ascending, then sets the lease, `status="running"` and `updated_at`.
   - **`heartbeat`:** a conditional update on `lease.owner == worker_id`. It returns whether a document matched.
   - **`log_event` sequence numbers:** use an atomic per-run counter, `$inc` on `migration_runs.event_seq`, so that two writers never collide. Don't use `count_documents`.
   - **`update_run` to a terminal status** (`completed`, `failed` or `cancelled`) also sets `expire_at = now + 14 days` on that run's events.
   - **`put_artifact`:** content whose JSON size exceeds 1 MB goes to GridFS (the async GridFS bucket). The artifact document then stores `gridfs_id`, and `get_artifact` loads it transparently.
   - **Documents** round-trip through `Model.to_doc()` / `Model.from_doc()`. Strip `_id` before `from_doc`.
   - **Errors:** a `DuplicateKeyError` becomes `core.interfaces.Conflict`, and a missing document raises `NotFound`.
3. **`AtlasToolStore(uri, db_name)`:**
   - It implements `ToolStore` on collection `tools`, with `(name, version)` unique and an index on `status`.
   - `record_use` is a single `$inc` / `$addToSet` update.
4. **`store/v2/strands_adapters.py`:**
   - `AtlasSessionRepository`: the full Strands `SessionRepository`, productionized from the S2 spike. Collections `agent_sessions`, `agent_agents` and `agent_messages`, with unique keys and a TTL on `expire_at`.
   - `AtlasStorage`: the Strands `strands.storage.Storage` protocol (read, write, list, delete, search) on collection `offload`, for the `ContextOffloader` plugin.
   - Both can take a `pymongo.MongoClient` (synchronous is fine inside Strands callbacks) or share the loop-thread client. Document which one you chose.
5. **`store/v2/factory.py`:**
   - `open_stores(settings: MvpSettings) -> tuple[RunStore, ToolStore]`: `settings.store_backend == "memory"` returns the fakes from `core.fakes`, and `"atlas"` returns the Atlas stores (Atlas requires `mongodb_uri`).
   - `close_stores(...)`.

## Tests

- **`tests/store_v2/test_run_store_contract.py` and `test_tool_store_contract.py`:**
  - Parametrized over `InMemoryRunStore` and `AtlasRunStore` (and the tool-store equivalents).
  - The Atlas case uses marker `mongo`, with URI from `PORTPILOT_TEST_MONGODB_URI` (`mongodb://127.0.0.1:27018/?directConnection=true`, the shared `portpilot-mongo` container, already running).
  - Each test uses a unique db named `pp_test_m_<hex>` and drops it afterwards.
  - Skip the Atlas case when the env var is unset.
- **Required cases:**
  - every protocol method;
  - lease exclusivity with 2 claimers racing in threads (exactly one wins);
  - reclaim after expiry;
  - `heartbeat` returns False for a non-owner;
  - event sequence numbers stay unique under 8 concurrent threads;
  - GridFS offload of a 2 MB artifact;
  - `Conflict` on duplicate step `seq` and duplicate tool version;
  - `from_doc` fidelity, including tz-aware datetimes.
- **`tests/store_v2/test_strands_adapters.py`** (marker `mongo`):
  - A Strands `Agent` with `RepositorySessionManager(AtlasSessionRepository)` and a scripted fake model (no LLM) runs 2 turns.
  - A brand-new Agent with the same `session_id` restores the identical messages.
  - `AtlasStorage` read/write/list/delete/search round trip.
  - Use the fake-model approach from `spikes/s2`, or a minimal `strands.models.Model` subclass that returns canned responses.

## Done

- `PORTPILOT_TEST_MONGODB_URI=mongodb://127.0.0.1:27018/?directConnection=true uv run pytest tests/store_v2` is green.
- A plain `uv run pytest` is green, with the `mongo` cases skipped.
- `uv run ruff check src tests` and `uv run ruff format --check src tests` are clean.
- Everything is committed on `mvp/m`.

## Stop conditions

- **An interface change is needed:** stop and report it; don't edit `core/`.
- **Time box:** about 2.5 hours.
