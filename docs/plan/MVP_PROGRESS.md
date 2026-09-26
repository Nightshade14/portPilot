# MVP implementation progress (orchestrator log)

The durable state of the parent orchestrator, used to resume after context compaction. It is authoritative over memory.

**Plan:** `docs/plan/MVP_PLAN.md`

**Subagents:** `claude-sonnet-5`, `reasoning_effort=high`. Briefs are in `docs/plan/mvp-lanes/`.

## Phase 0a: spikes (started 2026-09-26 14:20 EDT)

| Spike | Agent id | Worktree / branch | Status |
|---|---|---|---|
| S1 Atlas | 55a3b172 | ../portPilot-spike-s1 / spike/s1 | done, a47a3d7 |
| S2 Strands | 991d8f15 | ../portPilot-spike-s2 / spike/s2 | running |
| S3 Sandbox | a3be933d | ../portPilot-spike-s3 / spike/s3 | done, 993facc (goal 5 unverified) |

### S1 findings

- Native `$rankFusion` works with `$vectorSearch` and `$search` inputs on 8.0.32. The manual reciprocal-rank-fusion fallback is also implemented.
- `voyage-4` embeddings are 1024-dimensional.
- An `autoEmbed` index reached READY on M0, but embedding generation itself is unverified. We embed on our side anyway.
- The local image `mongodb/mongodb-atlas-local:latest` (8.3.11) starts. Connect with `mongodb://127.0.0.1:27019/?directConnection=true`.
- Index definitions are in `docs/spikes/S1_ATLAS.md` on `spike/s1`.

### S3 findings

- **Base image:** `debian:bookworm-slim@sha256:3783cc01…`. The sandbox image is 725 MB.
- **Run flags:** `--cpus 2 --memory 512m --pids-limit 256 --security-opt no-new-privileges --cap-drop ALL --read-only --tmpfs /tmp`. `/opt/pp/tools` must be its own writable volume.
- **Tool names:** DockerSandbox tools are named `sandbox_shell` and `sandbox_file_editor`.
- **Rootless BuildKit** (`moby/buildkit:v0.33.0-rootless`) needs `--privileged` on Docker Desktop. It must be a separate sidecar that the sandbox reaches over TCP.
- **Archive format:** trivy and dive both need a **docker-archive** (`type=docker`), not OCI.
- **Before and after optimizing the sample image:**
  - size: 368.7 MB → 48.0 MB;
  - CRITICAL CVEs: 228 → 9;
  - HIGH CVEs: 2391 → 111.
- **Allow-list:** 12 tools in `config/cli_allowlist.yaml`. shellcheck and buildctl have no published sha256, so they are refused.
- **Goal 5 (git checkpoint in the container):** not verified, because `git clone` was denied by tool approval. Lane S must verify it.

### Voyage

- The user's `VOYAGE_API_KEY` is a direct Voyage AI key. It gets a 403 from `ai.mongodb.com` and works against `https://api.voyageai.com/v1/embeddings`. Verified: `voyage-4`, 1024 dims; paraphrase similarity 0.893 against 0.377 for unrelated text.
- The `core/config.py` default is `VOYAGE_BASE_URL=https://api.voyageai.com/v1`.

### Parent work (committed on `main`)

- `0a8c56a`: core interfaces, fakes, API contract and lane briefs.
- Spike merges: `7a49380`, `3517762`, `4defb8a`.
- `e399d4a`: Lane A brief.

## Phase 1, Wave 1 (started 14:50 EDT; all subagents on claude-sonnet-5 at high effort)

| Lane | Agent id | Worktree / branch | Status |
|---|---|---|---|
| M Mongo state | 75cf03ed | ../portPilot-mvp-m / mvp/m | merged (ae02bba); 92 mongo contract tests green |
| K Knowledge | 7ce04612 | ../portPilot-mvp-k / mvp/k | merged (3be9c91); live Atlas+Voyage test passed; 2 prod indexes exist on portpilot_mvp.knowledge |
| S Sandbox | ef1f1afd | ../portPilot-mvp-s / mvp/s | merged (41ae075); Lead verified trivy/hadolint/dive installs + nmap refused; pp-buildkitd + pp-net left running |
| E Evals | 0fc24161 | ../portPilot-mvp-e / mvp/e | merged (a3daada); baselines E2 424MB 228 CRIT, E3 441MB 227 CRIT |
| F Frontend | b125ea09 | ../portPilot-mvp-f / mvp/f | merged (c3c9c96); Next 16, 28 vitest, fixtures mode |
| A Agent core | 7fcada94 | ../portPilot-mvp-a / mvp/a | running (delegated per user request) |

## Next steps (parent)

1. **As each lane finishes:**
   - Run its tests in its worktree and read the diff.
   - Merge it with `--no-ff` into `main`, in the order M → K → S → E → F → A.
   - Run the full `pytest` and ruff after each merge.
2. **Wave 2 briefs:**
   - `lane-t.md`: the tool library, the toolsmith (`author_tool` for the `AgentDeps` hook), `SandboxScriptTool` using the `pp_tool_run.py` protocol from lane-s.md, and seed tools including `http_contract_diff`. It doesn't include `repo_map`, which is Lane A's survey.
   - `lane-p.md`: FastAPI following `CONTRACT.md`, the worker (claim, heartbeat, `run_migration`), and deploy.
3. **Start Wave 2** once M and S are merged.
4. **Integration, owned by the Lead:**
   - `agent/deps.build_deps(settings)` wiring the real implementations;
   - the CLI: `portpilot worker`, `knowledge`, `runs`.

## Next steps (parent)

1. **While the spikes run:** draft `src/portpilot/core/{models,interfaces,config,events}.py` and the fakes on `main`.
2. **When all 3 spikes finish:**
   - Read each `docs/spikes/S*.md`.
   - Fill in the spike decisions in plan section 12.
   - Finalize `core/`.
   - Write the lane briefs `lane-{m,k,s,e,f,t,p}.md`.
   - Commit.
   - Create the lane worktrees.
   - Spawn Wave 1: lanes M, K, S, E and F.
3. **Parent builds Lane A in parallel.**

## Notes

- `VOYAGE_API_KEY` is missing from `.env`. The user needs to create a Model API key in the Atlas UI.
- The session ledger is unavailable because the crew log is disabled, so this file replaces it.

- 15:05 Lane A steered: author_tool(run_id, step_id, name, purpose, requirements) -> {ok,name,version,reason}; library emits tool_* events; new tool registered in same step.
- Wave 2 briefs written: lane-t.md, lane-p.md (spawn after M and S merge).
- Gotchas from K: $search filter on token field needs `equals`; mongot ~1s indexing lag after insert.

## Wave 2 (started 15:18 EDT)

| Lane | Agent id | Worktree / branch | Status |
|---|---|---|---|
| T Tool library | 1f7a76c3 | ../portPilot-mvp-t / mvp/t | running |
| P API + worker | adb65e6f | ../portPilot-mvp-p / mvp/p | merged (4259f98); 63 tests; real-HTTP smoke passes |

After A, T, P: Lead writes agent/deps.build_deps wiring (store.v2, knowledge, sandbox, toollib, author_tool, shell_guard, render_markdown, AtlasSessionRepository, AtlasStorage), then integration slices (Sync 2-4).

- 15:50 PAUSED by user. Both running lanes (A 7fcada94, T 1f7a76c3) steered to stop, commit WIP and write lane-*-status.md. Resume instructions: docs/plan/MVP_RESUME.md.
