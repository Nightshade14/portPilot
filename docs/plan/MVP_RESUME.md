# PortPilot MVP: pause point and how to resume

The build was paused by the user on 2026-09-26 at 15:50 EDT. `main` was at `8ea6ba7` at that point.

- **Plan:** `docs/plan/MVP_PLAN.md`.
- **Lane briefs:** `docs/plan/mvp-lanes/*.md`.
- **Orchestration log:** `docs/plan/MVP_PROGRESS.md`.
- **API contract:** `docs/api/CONTRACT.md`, which is frozen.

## 1. Where things stand

| Lane | What | State | Where |
|---|---|---|---|
| Spikes S1–S3 | Atlas hybrid search, Strands APIs, sandbox and BuildKit | merged | `main` |
| Core (lead) | `core/{models,interfaces,config,fakes}.py`, CONTRACT.md | merged, frozen | `main` |
| K | Knowledge: Voyage embedder, Atlas hybrid, vector and text search, dedupe, markdown views, CLI | merged `3be9c91` | `main` |
| E | Eval fixture repos E1–E3, baselines, scenarios, chaos script | merged `a3daada` | `main` |
| M | Atlas RunStore and ToolStore, Strands session repo and storage adapters | merged `ae02bba` | `main` |
| S | Docker sandbox, allow-list CLI installer, BuildKit, `pp_tool_run.py` runner | merged `41ae075` | `main` |
| F | Next.js frontend in `web/` | merged `c3c9c96` | `main` |
| P | FastAPI (`portpilot api`), worker (`portpilot worker`), `deploy/` | merged `4259f98` | `main` |
| **A** | **Agent core** (planner, selector, executor, guard, compaction, digest, reflect, loop) | **paused, not merged**. Uncommitted work was committed as "WIP Lane A: paused by user". | `../portPilot-mvp-a`, branch `mvp/a` (based on `e399d4a`, an old `main`) |
| **T** | **Tool library**: propose, validate and promote, `SandboxScriptTool`, builtins, seeds, toolsmith | **paused, not merged**. WIP was committed as "WIP Lane T: paused by user". | `../portPilot-mvp-t`, branch `mvp/t` (based on `c3c9c96`) |

Each paused lane was asked to write a status file: `docs/plan/mvp-lanes/lane-a-status.md` and `lane-t-status.md`, in their own worktrees. **Read those first.** If a file is missing, the lane stopped before writing it; check with `git -C ../portPilot-mvp-<l> log -3` and `git status`.

### Known issues at the pause

- **Lane A's live LLM test hung.** The test, `tests/agent/test_live_llm.py`, asks for slugify with tests on a tiny repo.
  - After 15 minutes the workspace had no code changes, only two sandbox pytest runs at 15:27. The lead killed the test at 15:39.
  - Suspected causes, unconfirmed:
    1. a model client with no request timeout;
    2. executor file writes landing outside the `LocalSandboxManager` workspace;
    3. a retry or reflect loop with no wall-clock guard.
- **Lane A predates the test gating on `main`** (`f1c75d0`): its branch has no `PORTPILOT_TEST_*` gate, and its live test only skips when `OPENROUTER_API_KEY` is missing. Since `.env` has that key, a plain `pytest` in that worktree calls the LLM. Run `pytest -m "not llm"` there until it's rebased or merged.
- **Lane A must implement** `deps.author_tool(run_id, step_id, name, purpose, requirements) -> {ok, name, version, reason}`. After a successful call, the new tool is registered in the same step: `tool_store.get` → `tool_library.as_agent_tool` → `register_dynamic_tool`. Lane T implements the other side in `toollib/toolsmith.py`.
- **Left running on purpose:** Docker container `pp-buildkitd` and network `pp-net`, which are the BuildKit sidecar. `portpilot-mongo` is shared, so don't stop it.

### Verification state of `main` at `8ea6ba7`

- A plain `uv run pytest` passes. `ruff check` and `ruff format --check` are clean.
- Opt-in suites that passed at merge time:
  - `PORTPILOT_TEST_DOCKER=1` for the sandbox;
  - `PORTPILOT_TEST_NETWORK=1` for the API smoke test;
  - `PORTPILOT_TEST_MONGODB_URI=mongodb://127.0.0.1:27018/?directConnection=true` for store_v2 (92 tests);
  - a live Atlas plus Voyage knowledge test, run once.
- **Not yet verified:** anything end to end. No real run has gone API → worker → agent → sandbox yet.

## 2. How to resume

Keep the rules from the rest of the build:
- Never push.
- Merge with `--no-ff`, and run the full `pytest` plus ruff after each merge.
- Never print `.env` values.
- Never touch `muybridge-livekit` or stop `portpilot-mongo`.
- No new Atlas search indexes. M0 allows 3 and `portpilot_mvp.knowledge` already uses 2.
- Temporary files go under `runs/_pytest/` or `runs/_checks/`, not `$TMPDIR`.

### Step 1: finish Lanes A and T (2 agents, in parallel)

Use `claude-sonnet-5`, `reasoning_effort=high`, `include_memory=false`, `include_lessons=true`. If the original conversations are still retained, use `spawn_continue` on `7fcada94` (A) and `1f7a76c3` (T). Otherwise start fresh with `spawn_run`, using task text like this:

- **A:** "You are Lane A of the PortPilot MVP, resuming paused work. Worktree `/Users/satyamchatrola/codes/personal/portPilot-mvp-a`, branch `mvp/a`.
  1. First run `git merge main`. Resolve conflicts in favour of `main` for everything outside `src/portpilot/agent/` and `tests/agent/`.
  2. Read `docs/plan/mvp-lanes/lane-a.md`, `lane-a-status.md` and `docs/plan/MVP_RESUME.md` §1.
  3. Fix the live-test hang: add a model request timeout (~120 s, max_retries=2), a run wall-clock guard, and an offline regression test.
  4. Gate the live test with `PORTPILOT_TEST_LLM=1`, then run it once under `timeout 600` and report its token usage.
  5. Commit on `mvp/a`."
- **T:** "You are Lane T, resuming paused work. Worktree `/Users/satyamchatrola/codes/personal/portPilot-mvp-t`.
  1. Read `lane-t.md` and `lane-t-status.md`.
  2. Finish the remaining items.
  3. Offline tests must pass, plus `PORTPILOT_TEST_DOCKER=1`, plus one `PORTPILOT_TEST_LLM=1` toolsmith run.
  4. Commit on `mvp/t`."

The lead reviews both results: diff paths within the lane's owned paths, tests, and the reported token usage.

### Step 2: merge (lead, no agents)

1. Merge in the order A → T, with `--no-ff`. After each merge, run `uv run pytest`, `uv run ruff check src tests evals` and `uv run ruff format --check src tests evals`.
2. Update `MVP_PROGRESS.md`.

### Step 3: integration wiring (lead, no agents)

The lead does this directly, because it touches every lane's surface:

- **`agent/deps.build_deps(settings)`**, wiring:
  - `store.v2.factory.open_stores`;
  - `AtlasKnowledgeStore` + `VoyageEmbedder`;
  - `sandbox.factory.open_sandbox` (manager + installer);
  - `SandboxToolLibrary` with `event_sink = run_store.log_event`;
  - `toolsmith.make_author_tool` → `AgentDeps.author_tool`;
  - `AtlasSessionRepository` and `AtlasStorage`.
- **The worker entry point** passes `build_deps` and `agent.loop.run_migration`.
- **Seeds:** call `toollib.seeds.seed_library` once at worker start. It's idempotent.

### Step 4: sync points (MVP_PLAN §7): lead plus up to 2 fix agents

Run each sync point yourself. Spawn at most 2 fix agents (sonnet-5, high), and only for failures that are independent and don't touch the same files.

1. **Sync 2:** a tiny repo end to end, going through `portpilot api` + `portpilot worker` + the web UI (`web/`, with `PORTPILOT_API_URL` pointed at the local API).
2. **Sync 3:** the E2 Dockerfile scenario. The agent must write its own Dockerfile tool, validate it and promote it. Then run E3 and confirm the tool is reused. Compare against `evals/baselines.json`.
3. **Sync 4:** `kill -9` on the worker mid-run, then resume, using `evals/chaos.py`. Also check compaction events and knowledge search over the lessons produced.

### Step 5: deployment and rehearsal (lead, plus 1 agent if needed)

1. Deploy `web/` to Vercel and set up the backend VM from `deploy/README.md`.
2. Rehearse the demo twice.

This step needs the user's decisions first.

## 3. Decisions still needed from the user

1. Which VM to use for the backend, and the domain for Caddy TLS.
2. Whether to publish the E1–E3 fixture repos to GitHub (the steps are in `evals/README.md`).
3. Whether to drop the scratch Atlas databases: `portpilot`, `portpilot_try2`, `portpilot_check_1..3`, and `portpilot_demo` from v0.
4. Whether to remove the merged worktrees (`../portPilot-spike-s*`, `../portPilot-lane-*`, `../portPilot-mvp-{m,k,s,e,f,p}`).

## 4. Agent budget summary

| Step | Agents |
|---|---|
| 1. Finish A and T | 2 in parallel (sonnet-5, high) |
| 2. Merge | 0 (lead) |
| 3. Wiring | 0 (lead) |
| 4. Sync fixes | at most 2, only for independent failures |
| 5. Deploy and rehearsal | 0–1 |
