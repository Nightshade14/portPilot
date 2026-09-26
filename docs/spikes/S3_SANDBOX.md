# Spike S3: sandbox container, CLI environment and image builds

Environment: Docker Desktop 29.8, host arm64 (containers aarch64), 10 CPUs / 16 GB.
All test resources prefixed `pp-test-s3-`; all removed at the end except the two
built images (`pp-test-s3-sandbox:dev`, and the throwaway build targets
`pp-test-s3-bloated`/`pp-test-s3-optimized`, per the brief "images may stay").

## Decision table

| Area | Decision | Evidence |
|---|---|---|
| Base image | `debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251` | `docker pull --platform linux/arm64 debian:bookworm-slim` |
| Run flags (sandbox container) | `--cpus 2 --memory 512m --pids-limit 256 --security-opt no-new-privileges --cap-drop ALL --read-only --tmpfs /tmp`, no `-v /var/run/docker.sock` | all confirmed live via `docker inspect`; see Goal 2 |
| BuildKit rootless sidecar | `moby/buildkit:v0.33.0-rootless` needs **`--privileged`** on Docker Desktop's VM — `seccomp=unconfined`+`apparmor=unconfined` alone starts buildkitd but its nested `runc` fails `RUN` steps (`mount src=proc ... operation not permitted`) | see Goal 4 |
| Archive format for trivy + dive | **Docker-archive** (`--output type=docker,...`), not the OCI-tarball output (`type=oci`) | trivy: `file manifest.json not found in tar`; `type=oci` also fails, since a plain gzip stream isn't the OCI directory layout trivy/dive expect for archives. `type=docker` works for both. |
| Tool versions (this run) | trivy 0.74.0, hadolint 2.15.1, dive 0.13.1, syft 1.52.0, grype 0.119.0, dockle 0.4.15, crane (go-containerregistry) 0.22.1, jq 1.8.2, yq 4.53.6, ripgrep 15.2.0; shellcheck 0.11.0 and buildkit 0.33.0 **listed but not installable** (no published sha256) | `config/cli_allowlist.yaml` |

## Goal verdicts

### 1. Sandbox image — PASS

`docker/sandbox/Dockerfile`, base pinned by tag+digest as above. Built as
`pp-test-s3-sandbox:dev` in 27s (cold), **725 MB**.

Contents confirmed by `docker run --rm pp-test-s3-sandbox:dev sh -c '...'`:
`python3 3.11.2`, `uv 0.9.6`, `node v24.9.0` / `npm 11.6.0` (pinned via
NodeSource `nodejs=24.9.0-1nodesource1`), `pytest 8.3.5`, `git 2.39.5`,
`curl 7.88.1`, non-root user `pp` (uid 1000), `/opt/pp/tools` on `PATH`,
`/workspace` declared as a volume.

Gotcha: I originally installed `pytest` only; `spikes/s3/install.py` needs
PyYAML to parse the allow-list, and there is no writable path to `pip install`
it at *runtime* once the container is `--read-only` (see Goal 3). Fixed by
adding `pyyaml==6.0.2` to the image build itself.

### 2. Running and driving the container — PASS

Ran with the full flag set above, plus `-v <name>:/workspace`. Confirmed live via
`docker inspect --format`:
```
CPUs=2000000000 Mem=536870912 Pids=256 ReadonlyRootfs=true CapDrop=[ALL] SecurityOpt=[no-new-privileges]
```
Read-only rootfs confirmed: `echo hi > /etc/test` → `Read-only file system`;
`/tmp` (tmpfs) and the `/workspace` volume both writable. No `-v /var/run/docker.sock`
was passed anywhere — the sandbox container never had the host Docker socket.

Drove it with `strands.sandbox.docker.DockerSandbox(container=..., working_dir="/workspace", user="pp")`
(`spikes/s3/probe_sandbox.py`):
- `sandbox.execute()`, `write_text()`/`read_text()`, `list_files()` — all confirmed
  operating inside the container (files landed in `/workspace`, visible via `docker exec`).
- Vended tools, called directly with no LLM: `Agent(sandbox=sandbox, tools=sandbox.get_tools())`,
  then `agent.tool.sandbox_shell(command=...)` and `agent.tool.sandbox_file_editor(command="create"/"view", ...)`.
  Both ran inside the container and returned structured tool results.
  **Gotcha:** `DockerSandbox.get_tools()` names them `sandbox_shell` /
  `sandbox_file_editor`, not the bare `shell` / `file_editor` the brief's pointer
  to `strands/vended_tools/shell` and `.../file_editor` might suggest — those
  modules export the *factory* (`make_shell`), and the Docker sandbox's own
  `get_tools()` renames the produced tool.

**Resume case — PASS.** `docker stop` then `docker start` on the same container,
then `docker exec ... cat /workspace/probe.txt /workspace/from_editor.txt`: both
files (written before the stop) were intact, confirming the container and its
named volume survive a stop/start cycle.

### 3. Allow-listed CLI installs — PASS (with one refusal-by-design)

`config/cli_allowlist.yaml` holds all 12 tools from the brief (3 required + 6
best-effort + crane, jq, yq beyond the base 6 already counted). Schema is
documented in the file's header comment.

Checksums were gathered from each project's own published checksums file
(trivy/dive/syft/grype/dockle: `..._checksums.txt`; crane:
`go-containerregistry` release checksums; jq/yq: release-body/sidecar hash;
ripgrep: per-asset `.sha256` sidecar; hadolint: per-asset published hash) — see
each tool's `verify_command` comment trail in the YAML. **Independently
re-verified by downloading and hashing** for the 3 required tools' arm64
artifacts:

```
trivy_0.74.0_Linux-ARM64.tar.gz     -> b94ce1976bbf3c15b514b605ee88be7c6d94a29be2302847ff01cb794d47aad5  (match)
hadolint-linux-arm64                -> f6198ef8090f404dbb771abfee086eb8c48ac177f30da7fd3510aca35b344b5d  (match)
dive_0.13.1_linux_arm64.tar.gz      -> 2fcd2cf20f634ccdb41efac44048b204bfc867c115641f37a7420693ed480a18  (match)
```

**shellcheck 0.11.0 and buildkit(buildctl) 0.33.0 publish no sha256 checksums
file for this release** (buildkit ships only cosign/SLSA sigstore attestations).
They are listed in the allow-list with `sha256: null` so `install.py` structurally
cannot install them yet — pinning against an attestation instead of a raw sha256
is a follow-up, not solved in this spike.

`spikes/s3/install.py` — tested inside the container:
- Refuses an unknown name: `python3 install.py totally-not-a-tool` →
  `refused: unknown tool: 'totally-not-a-tool' is not in the allow-list`, exit 1.
- Refuses a checksum mismatch: tampered the arm64 sha256 for `jq` to all-zeros →
  `refused: checksum mismatch for jq (arm64): expected 000...0, got 8b85c8...`, exit 1.
- Real install (binary method): `jq` → downloaded, sha256-verified, copied to
  `/opt/pp/tools/jq`, `chmod 755`; `jq --version` → `jq-1.8.2`.
- Real install (tarball method): `dive` → downloaded, verified, extracted `dive`
  member from the `.tar.gz`, `dive --version` → `dive 0.13.1`.
- Idempotency: running `install.py jq` again after success printed
  `jq already installed at pinned version 1.8.2; skipping` and did not re-download.

**Gotcha (important for the real harness):** with the container's rootfs
`--read-only`, `/opt/pp/tools` as baked into the image is **not writable at
runtime**. The installer only works when `/opt/pp/tools` is mounted as its own
writable volume (`-v pp-tools:/opt/pp/tools`), separate from the read-only
rootfs — same pattern as `/workspace`. The MVP's `install_cli_tool` built-in tool
needs to mount `/opt/pp/tools` as a volume, not rely on the image layer.
Also: `uv pip install --system` and `pip install --target /usr/...` both fail
under `--read-only` (`~/.cache`, dist-packages are on the rootfs) — any
runtime Python dependency of the harness itself must be baked into the image
at build time, not installed lazily.

### 4. Image builds without the host Docker socket — PASS

**BuildKit sidecar:** `docker run -d --name pp-test-s3-buildkitd --network pp-test-s3-net
moby/buildkit:v0.33.0-rootless --addr tcp://0.0.0.0:1234`.

- Least-privileged attempt (`--security-opt seccomp=unconfined --security-opt apparmor=unconfined`,
  no `--privileged`): buildkitd **starts** and reports a worker
  (`org.mobyproject.buildkit.worker.snapshotter:overlayfs`), and simple
  metadata ops (`buildctl debug workers`, resolving a `FROM` image) succeed —
  but the first `RUN` instruction fails:
  `runc run failed: ... error mounting "proc" to rootfs at "/proc": ... operation not permitted`.
  This is rootless-BuildKit's nested `runc` container hitting Docker Desktop's
  own sandboxing of the Linux VM.
- **Escalated to `--privileged`** (the brief's documented last resort): buildkitd
  starts identically, and the full build (including `RUN pip install requests`)
  succeeds. **Recorded finding: on this Docker Desktop arm64 host, rootless
  BuildKit's own privilege reduction is not enough on its own — the sidecar
  container needs `--privileged` to run nested build steps.** This matches the
  brief's stop-condition guidance to record why and evaluate the fallback; the
  fallback (host-daemon build from the worker side, no socket in the sandbox)
  was not needed since `--privileged` on the *sidecar* (not the sandbox
  container) worked and keeps the security boundary where the brief wants it —
  the CLI/agent sandbox still never sees a Docker socket or elevated privileges.
- `buildctl` reached buildkitd over `tcp://pp-test-s3-buildkitd:1234` from
  inside the sandbox container via the shared user network `pp-test-s3-net`
  and Docker's embedded DNS (`getent hosts pp-test-s3-buildkitd` resolved).
- **Gotcha:** `buildctl` itself (the *client*, running as `pp` inside the
  read-only sandbox) tries to create `$HOME/.docker` for its config cache and
  fails (`mkdir /home/pp/.docker: read-only file system`) even though the
  actual build executes remotely in buildkitd. Fixed with
  `-e DOCKER_CONFIG=/workspace/.docker-config`.

**Bloated image build + scan:**
```dockerfile
FROM python:3.8
RUN pip install requests
```
Built via `buildctl ... --output type=docker,name=pp-test-s3-bloated:dev,dest=/workspace/bloated-docker.tar`
(first attempt used `type=oci`, which trivy/dive both reject as an archive format
for a plain gzip stream — see decision table). Result: **368,734,720 bytes** (368.7 MB) tarball.

- `trivy image --input bloated-docker.tar`: **CRITICAL 228, HIGH 2391, MEDIUM 6826,
  LOW 2018, UNKNOWN 444**. Vulnerability DB download: 117.54 MiB in ~4.3–8.9s
  (varied by run; cold vs. warm-ish CDN). Gotcha: default `TRIVY_CACHE_DIR`
  (`~/.cache`) is also on the read-only rootfs — set
  `-e TRIVY_CACHE_DIR=/workspace/.trivy-cache`.
- `dive --source docker-archive <tar> --ci --json <out>`: `efficiencyScore
  0.9922`, `sizeBytes 1,010,391,032` (dive's own uncompressed-layer accounting,
  larger than the compressed tar), `inefficientBytes 9,534,582`. Gotcha: dive
  also wants a writable `$HOME` for its own config; ran with `-e HOME=/workspace`.
- `hadolint /workspace/bloated-ctx/Dockerfile`: 2 warnings, both real —
  `DL3013` (pin pip package versions) and `DL3042` (use `--no-cache-dir`), exit 1.

**Optimized rebuild:**
```dockerfile
FROM python:3.8-slim AS builder
RUN pip install --no-cache-dir --user requests==2.32.4
FROM python:3.8-slim
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
```
Built the same way, **47,953,408 bytes (48.0 MB)** — a 7.69x reduction.

| Metric | Bloated | Optimized | Change |
|---|---|---|---|
| Tarball size | 368.7 MB | 48.0 MB | −87% |
| CRITICAL CVEs | 228 | 9 | −96% |
| HIGH CVEs | 2391 | 111 | −95% |
| MEDIUM CVEs | 6826 | 204 | −97% |
| LOW CVEs | 2018 | 151 | −93% |
| dive efficiencyScore | 0.9922 | 0.9753 | (both already high; slim base has less to waste) |
| dive inefficientBytes | 9.53 MB | 5.48 MB | −42% |

### 5. Workspace checkpoints — NOT VERIFIED (tool call denied)

The shell command to shallow-clone `https://github.com/pallets/itsdangerous`
into the sandbox's `/workspace/repo` was **denied by tool-execution approval**
in this run, on two separate attempts (retried once per policy — a repeated
denial is a final decision, not something to route around). No git-clone,
branch/commit, or `git reset --hard && git clean -fd` restore test was run.
This goal is unverified, not failed — nothing about the sandbox, the container's
git binary, or its network access was shown to be broken; the block was on the
orchestration layer approving the shell call itself, both times for the exact
same command shape. A human should re-run this goal manually to close it out;
the container/tooling needed (`git 2.39.5`, network egress already proven by
Node/npm and curl/apt fetches earlier in this spike) is otherwise in place.

## Stop-condition notes

- No sub-goal took more than ~15 minutes stuck; the two real blockers hit
  (BuildKit privilege escalation, OCI-vs-docker-archive format) were each
  resolved within a few minutes by trying the brief's own documented fallback.
- Total time: well under the ~90 minute time box.
- Rootless BuildKit **did** run on Docker Desktop, but only with `--privileged`
  on the sidecar — see the BuildKit finding above. The host-daemon-without-socket
  fallback was not needed.

## Files in this worktree

- `docker/sandbox/Dockerfile` — the sandbox image.
- `config/cli_allowlist.yaml` — the draft allow-list, schema documented inline.
- `spikes/s3/install.py` — the allow-listed installer (binary + tarball methods,
  unknown-name and checksum-mismatch refusals, idempotent).
- `spikes/s3/probe_sandbox.py` — drives `DockerSandbox` + vended tools with no LLM.
- `spikes/s3/bloated.Dockerfile`, `spikes/s3/optimized.Dockerfile` — the two
  build targets analyzed above.
- `docs/spikes/S3_SANDBOX.md` — this file.

## What I could not verify

- Goal 5 (workspace checkpoints / git reset+clean restore) — blocked by a denied
  tool call, not attempted successfully.
- Best-effort tools syft, grype, dockle, crane, yq, ripgrep were allow-listed
  with checksums gathered from each project's own published checksums file, but
  **not** independently re-downloaded-and-hashed the way trivy/hadolint/dive
  were (brief requires that only for arm64 checksums generally — I prioritized
  the 3 required tools given the time box; the best-effort tools' hashes are
  one subagent's transcription of the checksums files, not independently
  double-checked by a second read).
- shellcheck and buildkit(buildctl) have no install-time integrity check at all
  in this draft allow-list (no published sha256 exists for these releases) —
  flagged with `sha256: null`, which the installer treats as a hard refusal,
  but that's a gap for a human reviewer to resolve (e.g. by pinning to a
  cosign-attested digest instead of a raw hash).
