# Lane P: API server, worker and deployment

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-p`, on branch `mvp/p`.
- **Wave:** 2.
- **Read first:**
  - `docs/api/CONTRACT.md`, which is frozen: implement it exactly;
  - `docs/plan/MVP_PLAN.md` §2, §3.7 and §3.9;
  - `src/portpilot/core/{models,interfaces,fakes,config}.py`, which are frozen;
  - `src/portpilot/store/v2/` (merged; `open_stores`) and `src/portpilot/knowledge/`.

## Owns

- `src/portpilot/api/` and `src/portpilot/worker/` (new).
- `deploy/`.
- `tests/api/` and `tests/worker/`.
- In `src/portpilot/cli.py`, you may add only two commands, `api` and `worker`, as thin wrappers.

## Build

### 1. `api/app.py`

`create_app(deps: ApiDeps) -> FastAPI`, where `ApiDeps` holds `run_store`, `tool_store`, `knowledge`, `sandbox | None` and `settings`.

**Every endpoint and shape in `CONTRACT.md`.** `datetime` values are serialized as ISO strings.

**Auth:**
- A bearer token compared with `hmac.compare_digest` against `settings.api_token`.
- The app refuses to start when `api_token` is unset, unless `PORTPILOT_API_INSECURE_DEV=1` is set, in which case it logs a loud warning.

**Request handling:**
- **CORS:** allow only `settings.api_cors_origins`.
- **Errors:** always use the contract's error shape, including validation errors (a custom 422 handler with the contract codes).
- **`POST /runs`:**
  - validates `repo_url` against the contract regex, with local paths only when `PORTPILOT_ALLOW_LOCAL_REPOS=1`, and validates `goal`;
  - creates `Run(run_id=new_id("run"), status="queued")` and logs `run_created`;
  - is rate-limited by an in-memory token bucket keyed by the token: 10 runs per hour, then `429`.

**Run controls:**
- **pause:** sets `control="pause"`. A queued run goes straight to `paused`.
- **resume:** only for a paused run. Sets it back to `queued` with `control=None`; anything else returns `409`.
- **cancel:** sets `control="cancel"`. A queued or paused run goes straight to `cancelled`.

**Responses and misc:**
- **`RunSummary`:** computed from the steps.
- **download:** `sandbox.export_archive(run_id)`, returning `503` when no sandbox is configured.
- **OpenAPI:** `python -m portpilot.api.openapi` writes `docs/api/openapi.json`. Commit the output.

### 2. `api/deps.py`

`build_api_deps(settings)` uses `store.v2.factory.open_stores`, `knowledge` (`AtlasKnowledgeStore` + `VoyageEmbedder`, or the in-memory versions when `store_backend == "memory"`), and the sandbox factory.

If `portpilot.sandbox` doesn't expose `open_sandbox` yet on your base, guard the import and set `sandbox=None`.

### 3. `worker/main.py`

`Worker(settings, build_deps: Callable[[], Any], run_fn: Callable[[deps, run_id, worker_id], None], poll_s=3)`:

**The loop:**
1. `claim_run(worker_id, lease_s)`.
2. Start a heartbeat thread that runs every `lease_s / 4`. When `heartbeat` returns False, it sets a `lease_lost` Event, which `run_fn` can read through `deps`.
3. Call `run_fn`.
4. Release.
5. If `run_fn` raised, set `status="failed"` with the error, and log the `failed` event.

**Shutdown:** SIGTERM and SIGINT make it stop claiming, let the current run reach its next checkpoint, then exit. A second signal exits immediately; the lease expires on its own and the run is reclaimed.

**Entry point:** `main()` uses `run_fn=portpilot.agent.loop.run_migration`, imported lazily; that package is from Lane A. If the import fails, exit with a clear message.

### 4. CLI

- `portpilot api --host 127.0.0.1 --port 8000` runs uvicorn. The host defaults to `127.0.0.1`, because Caddy terminates TLS in front of it.
- `portpilot worker` runs the worker.

### 5. `deploy/`

- **`README.md`,** a VM runbook for Ubuntu 24.04 on a disposable VM: Docker, uv, the repo, `.env`, building the sandbox image, starting BuildKit, systemd units, and Caddy with automatic TLS for `api.<domain>`. It must also cover:
  - a security checklist: firewall with only 80 and 443 open, no other credentials on the VM, the token rotation procedure;
  - Vercel environment variables for `web/`.
- **`systemd/portpilot-api.service`** and **`systemd/portpilot-worker.service`**, with `Restart=always`. The worker restart is what drives resume after a kill.
- **`Caddyfile`** and **`compose.yml`** for Caddy and the BuildKit sidecar only. The API and worker run on the host, because they drive the Docker CLI. Never mount the Docker socket into any container.

## Tests

**`tests/api/`:** FastAPI `TestClient` with the in-memory fakes. Cover:
- every endpoint;
- the error shape for 401, 404, 409, 422 and 429;
- auth on every route except health;
- repo URL validation;
- the pause, resume and cancel transitions;
- event pagination with `after_seq`;
- download, with a fake sandbox;
- the OpenAPI file is up to date.

**`tests/worker/`**, with a fake `run_fn`:
- claims, heartbeats and releases;
- a lost lease stops the run;
- an exception marks the run failed;
- a second worker reclaims a run after the lease expires;
- graceful SIGTERM, tested in a subprocess.

**An end-to-end smoke test:** start `portpilot api` on port 8765 with in-memory stores and insecure dev mode, create a run through httpx, and read it back.

## Done

- `uv run pytest tests/api tests/worker` is green.
- A plain `uv run pytest` is green.
- Ruff is clean.
- `docs/api/openapi.json` is committed.
- Everything is committed on `mvp/p`.

## Stop conditions

- **Contract or interface change needed:** stop and report it.
- **Time box:** about 2.5 hours.
