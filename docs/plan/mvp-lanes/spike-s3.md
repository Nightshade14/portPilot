# Spike S3: sandbox container, CLI environment and image builds

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-spike-s3`, on branch `spike/s3`.
- **Read first:** `docs/plan/MVP_PLAN.md` sections 3.2, 3.8 and 3.9, and the S3 bullet in section 7.
- **Strands source:** strands-agents 1.57.1 is installed in your worktree's `.venv`. Read these from its source:
  - `strands/sandbox/docker.py` (the `DockerSandbox`);
  - `strands/vended_tools/shell` and `strands/vended_tools/file_editor`.
- **Where your work goes:**
  - the draft sandbox image in `docker/sandbox/Dockerfile`;
  - the draft allow-list in `config/cli_allowlist.yaml`;
  - probe code in `spikes/s3/`;
  - findings in `docs/spikes/S3_SANDBOX.md`.
- **Don't touch:** `src/` or `tests/`.
- **No secrets:** this spike needs none, so don't read `.env`.

## Environment

- Docker Desktop, engine 29.8. The host is arm64, so containers are aarch64, and the kernel is 6.19 or newer.
- 10 CPUs and 16 GB of memory.
- Name everything you create with the prefix `pp-test-s3-`, and remove it all at the end. Images may stay.

## Goals

Verify each goal by running it, and record the exact commands and outputs.

### 1. The sandbox image

Base it on Debian slim, pinned by tag and digest. It needs:
- git, curl and ca-certificates;
- python3, uv and pytest;
- node and npm, pinned;
- a non-root user `pp`;
- `/workspace` as a named volume, and `/opt/pp/tools` on `PATH`.

Build it as `pp-test-s3-sandbox:dev` and record its size.

### 2. Running and driving the container

**Start it with limits:**
- `--cpus`, `--memory` and `--pids-limit`;
- `--security-opt no-new-privileges` and `--cap-drop ALL`;
- a read-only root filesystem with a tmpfs `/tmp`, if feasible;
- no Docker socket.

**Drive it from Python** with `strands.sandbox.docker.DockerSandbox(container=..., working_dir="/workspace", user="pp")`:
- Run commands, and write, read and list files.
- Call the vended `shell` and `file_editor` tools through an Agent created with `sandbox=`, without an LLM (direct invocation, for example `agent.tool.shell(...)`). Confirm they run inside the container.

**The resume case:** confirm the container can be stopped, started and reattached with its volume intact.

### 3. Allow-listed CLI installs

**Tools:**
- required: trivy, hadolint, dive;
- best effort: syft, grype, dockle, crane, jq, yq, ripgrep, shellcheck, buildctl.

**For each tool:**
1. Pick the current stable version from its GitHub releases.
2. For linux arm64 and linux amd64, record:
   - the download URL;
   - the sha256, taken from the project's published checksums file;
   - the install method (a tarball and the path to extract, or a single binary);
   - a verify command, such as `trivy --version`.
3. Verify the arm64 checksums by downloading the files.

Write the results to `config/cli_allowlist.yaml`, with its schema documented in the file.

**Installer:** write `spikes/s3/install.py`, which installs a tool by name inside the container:
- downloads there and checks the sha256;
- installs into `/opt/pp/tools`;
- is idempotent.

It must refuse unknown names and refuse a checksum mismatch. Test both refusals.

### 4. Image builds without the host Docker socket

**Set up BuildKit:**
1. Run a rootless BuildKit sidecar, `moby/buildkit:<pinned>-rootless`, on a user network `pp-test-s3-net`, listening on TCP.
2. Find the minimum security options Docker Desktop needs for it:
   - try the least-privileged first: unconfined seccomp and apparmor;
   - use `--privileged` only as a last resort;
   - record which one worked.

**Build and scan the bloated image:**
1. From the sandbox, use `buildctl --addr tcp://...` to build a deliberately bloated Dockerfile. For example:
   - `FROM python:3.8`, the full image;
   - `pip install requests`;
   - no multi-stage build, and apt caches left in place.

   Write the result to a docker-archive or OCI tarball in `/workspace`.
2. Analyze the tarball:
   - `trivy image --input <tar>`: record CVE counts by severity, and the vulnerability database's download size and time.
   - `dive`: find the right source flag or prefix for archives and its `--ci` mode, and record image efficiency and wasted bytes.
   - `hadolint` on the Dockerfile.

**Optimize and compare:**
1. Write an optimized Dockerfile: slim base, multi-stage, with cleanup.
2. Rebuild it.
3. Record size and CVE counts before and after.

### 5. Workspace checkpoints

Inside the container:
1. Shallow-clone a small public repo into `/workspace/repo`, for example `https://github.com/pallets/itsdangerous --depth 1`.
2. Create branch `portpilot/test`, make a change, commit it, and record the SHA.
3. Make another change.
4. Restore to the SHA with `git reset --hard` plus `git clean -fd`, in the sandbox workspace only.
5. Verify the restore.

## Deliverable

`docs/spikes/S3_SANDBOX.md`, containing:
- **A decision table covering:**
  - the base image and its digest;
  - the run flags;
  - the BuildKit options that worked;
  - an archive format that both trivy and dive accept;
  - the version of each tool.
- **The measured numbers, every exact error, and gotchas.**

Also commit the draft Dockerfile, the draft allow-list and the probe scripts on `spike/s3`.

## Stop conditions

- **Done:** goals 1–5 each have a verdict backed by evidence.
- **If rootless BuildKit can't run on Docker Desktop at all:**
  - record why;
  - evaluate the fallback of building on the host daemon from the worker side, without mounting the socket into the sandbox.
- **Stuck:** spend no more than about 15 minutes stuck on any one sub-goal.
- **Time box:** about 90 minutes.
