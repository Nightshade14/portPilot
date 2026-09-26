# Lane B brief: persistence + checkpoints

Also read: `src/portpilot/store/__init__.py`, `src/portpilot/harness/context.py`, stubs `store/memory.py`, `store/atlas.py`, `harness/tools/persist_checkpoint.py`.

You own: `src/portpilot/store/memory.py`, `store/atlas.py`, a new `store/seed.py`, `harness/tools/persist_checkpoint.py`, `tests/test_store*.py`, `tests/test_checkpoint*.py`.

**Priority:** Lane C is blocked on `InMemoryStore`. Implement and test it first, and commit it on its own before starting `AtlasStore`.

## Semantics (identical in both stores)

- **Ids and return values.** Run ids are `run_<12 hex>`; artifact ids are `art_<12 hex>`. Returned docs are plain dicts with no Mongo `_id`. The memory store returns deep copies. Timestamps are timezone-aware UTC `datetime`s. Unknown ids raise `NotFound` (from `store.base`).
- **Runs.**
  - `create_run` → `{run_id, source_path, policy_version, status:"running", current_milestone:None, attempt:0, created_at, updated_at}`.
  - `update_run` sets the given fields and bumps `updated_at`.
- **Milestones.**
  - Docs look like `{run_id, name, attempt, status:"started"|"completed", started_at, completed_at, artifact_ids}`.
  - `start_milestone` also sets `run.current_milestone`.
  - `completed_milestones` returns `[(name, attempt)]` in completion order.
- **Artifacts.**
  - `put_artifact` returns the id.
  - `get_artifact` returns `{artifact_id, run_id, kind, attempt, content, created_at}`.
  - `latest_artifact` returns the newest by `created_at`, or `None`; insertion order breaks ties.
  - `artifacts(run_id, kind=None, attempt=None)` returns matches in ascending order.
- **Policies.** Return `Policy` instances.
  - `save_policy` raises `StoreError` on a duplicate `(name, version)`.
  - `get_policy(name, None)` returns the single `active` policy; `NotFound` if there is none.
  - `list_policies` sorts ascending by version.
  - `set_policy_status` sets `status` and `decision`.
- **Events.**
  - Each event is `{run_id, type, milestone, payload, ts, seq}`, where `seq` increases monotonically.
  - `events()` sorts by `(ts, seq)`.
- **`AtlasStore(uri, db_name)`** (pymongo, direct find/insert/update, no ORM).
  - Collections: `migration_runs`, `milestones`, `artifacts`, `policies`, `events`.
  - Indexes created on init:
    - `run_id` on every run-scoped collection, unique on `migration_runs`;
    - unique `artifact_id`;
    - unique `(name, version)` on policies;
    - `(run_id, ts)` on events.
  - Map `DuplicateKeyError` to `StoreError`. Use `serverSelectionTimeoutMS=8000`.
- **`store/seed.py`:** `seed_policy(store, path, name="flask-to-hono", version=1) -> Policy`. The body is the markdown file. `rules` are the `- ` bullet lines under a `## Rules` heading. It saves the policy as `active` and is idempotent: if the policy already exists, return it.
- **`persist_checkpoint`** (keep `@tool` and its signature). Using `ctx().store`:
  - `log_event(run_id, "checkpoint", milestone, {"note": note})`;
  - `update_run(run_id, last_checkpoint={milestone, note, ts})`;
  - return `"ok"`.

## Tests

`tests/test_store_contract.py` is one suite parametrized over a `store` fixture:
- `memory` always runs.
- `atlas` runs only when `MONGODB_URI` is set (otherwise skipped, `@pytest.mark.atlas`). It uses a unique throwaway db per session, dropped at teardown.

Coverage:
- Every method, including NotFound, duplicates, the active-policy lookup and ordering.
- A resume test: after `source_analysis` and `generation` complete, a fresh `AtlasStore` on the same db (or the same memory instance) returns the same completed milestones, artifacts and active policy.
- `seed_policy` idempotency.
- `persist_checkpoint` via `bind(InMemoryStore())`.

The Atlas cluster is still provisioning, so the Atlas tests will skip. Make that code correct by careful reading.
