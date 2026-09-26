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

### Parent work done (uncommitted on `main`)

- `src/portpilot/core/{__init__,models,interfaces,config,fakes}.py`
- `tests/core/test_fakes.py`
- Full suite: 99 passed, 22 skipped. Ruff is clean.

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
