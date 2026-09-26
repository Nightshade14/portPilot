# Lane S: Sandbox and CLI environment

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-s`, on branch `mvp/s`.
- **Wave:** 1.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` §3.2, §3.8 and §3.9;
  - `src/portpilot/core/{models,interfaces,fakes,config}.py`, which are frozen;
  - `docs/spikes/S3_SANDBOX.md`, `docker/sandbox/Dockerfile`, `config/cli_allowlist.yaml` and `spikes/s3/*.py`, all verified in the spike.

## Owns

- `src/portpilot/sandbox/` (new package).
- `docker/sandbox/`.
- `config/cli_allowlist.yaml`. It is human-reviewed data, and the agent can never write to it at runtime.
- `tests/sandbox/`.

## Facts established by the spike

- **Base image:** `debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251`.
- **Run flags:** `--cpus 2 --memory 512m --pids-limit 256 --security-opt no-new-privileges --cap-drop ALL --read-only --tmpfs /tmp`.
  - Never mount a Docker socket.
  - `/opt/pp/tools` needs its own writable volume.
  - Tool caches (uv, trivy, dive) need writable paths under a volume or tmpfs.
- **Strands tool names:** `DockerSandbox(container, working_dir, user)` names its tools `sandbox_shell` and `sandbox_file_editor`.
- **BuildKit:**
  - A rootless BuildKit sidecar, `moby/buildkit:v0.33.0-rootless`, needs `--privileged` on Docker Desktop. It is a separate container reached over TCP on a user network.
  - trivy and dive both require **docker-archive** output (`--output type=docker,dest=...`), not OCI.
- **Allow-list:** shellcheck and buildctl have no published sha256, so the installer refuses them.
  - Bake `buildctl` into the image instead: `COPY --from=moby/buildkit:v0.33.0 /usr/bin/buildctl ...`, pinned by digest.
- **Not yet verified:** a git checkpoint and restore inside the container (S3's goal 5). You must verify it.

## Build

1. **`docker/sandbox/Dockerfile`:**
   - Finalize it: add `buildctl`, `pyyaml` (already there), and the tool runner at `/opt/pp/bin/pp_tool_run.py`.
   - Build it as `portpilot-sandbox:dev` via `portpilot.sandbox.image.build_image()`, which runs a `docker build` subprocess.
2. **`manager.py`:** `DockerSandboxManager(image, network="pp-net", allow_local_repos=False)` implements `core.interfaces.SandboxManager`.
   - Use the docker CLI through `subprocess.run([...])` with argument lists. Never use `shell=True` on the host.
   - **Names:** container `pp-sbx-<run_id>`; volumes `pp-ws-<run_id>` (`/workspace`) and `pp-tools-<run_id>` (`/opt/pp/tools`).
   - **`ensure()`:**
     - Creates the container, or starts it if it is stopped. It is idempotent.
     - On first creation, it shallow-clones `repo_url` into `/workspace/repo` with a timeout.
     - Then it sets the git identity, creates branch `portpilot/<run_id>` and makes an initial commit.
     - When `allow_local_repos` is set and `repo_url` is a local directory, copy it in with `docker cp` instead. This is for dev and tests only.
   - **`exec()`:** `docker exec -i -u pp -w <cwd>`, with a timeout that kills the process, and stdout/stderr each capped at 1 MB (mark truncation).
   - **Files:** `write_file` and `read_file` go through `exec` with stdin, so content never passes through a host shell.
   - `sandbox()` returns a Strands `DockerSandbox`.
   - **Git:** `commit` returns the SHA; `restore` runs `reset --hard` plus `clean -fd`; `export_archive` runs `git archive --format=tar.gz HEAD` and returns the bytes.
   - `stop` and `destroy` also remove the volumes.
   - **Validation:** validate `run_id` against `^[a-z0-9_-]{3,64}$`, and repo URLs against the contract regex in `docs/api/CONTRACT.md`.
3. **`installer.py`:** `DockerCliInstaller(manager, allowlist_path=CLI_ALLOWLIST_PATH)` implements `CliInstaller`.
   - It installs inside the container: curl download, `sha256sum` check, extract or copy into `/opt/pp/tools/bin`.
   - A manifest at `/opt/pp/tools/manifest.json` makes it idempotent.
   - An unknown name, a missing sha256 for the architecture, or a checksum mismatch returns `InstallResult(refused=True, reason=...)`.
   - `check_environment` reports OS, arch, free disk and memory, installed tools and versions, allow-listed names, and repo languages (a count of file extensions under `/workspace/repo`).
4. **`buildkit.py`:**
   - `ensure_buildkit()` runs the `pp-buildkit` sidecar (privileged, pinned) on `pp-net`, listening on `tcp://0.0.0.0:1234`. It is idempotent.
   - `build_image(manager, run_id, context="/workspace/repo", dockerfile="Dockerfile", tag=...) -> dict` runs `buildctl` inside the sandbox, outputs docker-archive to `/workspace/.pp/images/<tag>.tar`, and returns `{tar_path, size_bytes, seconds}`.
   - Add a docstring naming the risk: the privileged BuildKit sidecar is acceptable only on the disposable backend VM.
5. **`runner/pp_tool_run.py`**, copied into the image. The protocol is frozen, because Lane T relies on it:

   ```text
   python3 /opt/pp/bin/pp_tool_run.py --dir /workspace/.pp/tools/<name>/<version> --timeout 300
   ```

   - Reads the params JSON from stdin.
   - Imports `main.py` from `--dir` and calls `run(params) -> dict`.
   - Prints exactly one JSON line to stdout: `{"ok": true, "result": {...}}` or `{"ok": false, "error": "...", "traceback": "..."}`.
   - Exit code 0 when `ok`, 1 otherwise, and 124 on timeout.
   - Caps the result at 256 KB (`{"ok": false, "error": "result too large"}`).
   - Runs the tool with `cwd=/workspace/repo`.
6. **`shell_guard.py`:** `looks_like_install(cmd: str) -> str | None` returns a reason for commands like:
   - `apt(-get) install`, `apk add`, `yum`/`dnf install`, `brew install`;
   - `pip install` outside a venv, `npm i -g` / `npm install -g`;
   - `curl … | sh|bash`, `wget … | sh`.

   Unit-test true positives and false positives, for example `npm install` in the repo is allowed.
7. **`factory.py`:** `open_sandbox(settings) -> tuple[SandboxManager, CliInstaller]`.

## Tests

- **Unit, no marker:** `shell_guard`, allow-list parsing, run_id and repo URL validation, and the runner protocol (run `pp_tool_run.py` locally on a temp tool dir).
- **`docker` marker:**
  - `ensure` and reattach after `docker stop`, with the volume intact.
  - `exec` timeout and output caps.
  - `write_file` and `read_file` with quotes and newlines.
  - Commit and restore round trip (the missing goal 5).
  - `export_archive` returns a valid tar.gz.
  - Installing trivy, hadolint and dive works; running the install again is a no-op.
  - Refusals: an unknown name, a checksum mismatch (use a temp allow-list with a wrong hash).
  - `check_environment`.
  - The `DockerSandbox` tools route into the container.
  - For `ensure`, use `allow_local_repos` with a local test repo, so no network is needed.
- **`docker` + `network` marker:**
  - A clone from `https://github.com/pallets/itsdangerous`.
  - A BuildKit build of `spikes/s3/bloated.Dockerfile` to a docker-archive, then trivy and dive run on the tarball.
  - If the approval prompt blocks network calls from your shell, report it. Don't work around it.
- **Naming and cleanup:** every test container starts with `pp-test-s-`, and fixtures remove them.

## Done

- `uv run pytest tests/sandbox -m "docker and not network"` is green.
- The `network` tests have passed once.
- A plain `uv run pytest` is green.
- Ruff is clean.
- Everything is committed on `mvp/s`.

## Stop conditions

- **Interface change needed:** stop and report it; don't edit `core/`.
- **Time box:** about 3 hours.
