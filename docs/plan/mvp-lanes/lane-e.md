# Lane E: Evals and fixture repos

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-e`, on branch `mvp/e`.
- **Wave:** 1.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` §1.1, §7 (the sync table) and §8 (Lane E);
  - `docs/api/CONTRACT.md`, which is frozen;
  - `src/portpilot/core/models.py`;
  - `docs/spikes/S3_SANDBOX.md`, for how trivy, dive and hadolint were run.

## Owns

- `evals/` (new).
- `tests/evals/`.

## Build

1. **Three fixture repos**, one directory each, each a standalone project with its own README, tests and Dockerfile, and no references to this repo:
   - **`evals/repos/e1-flask-profile-api/`:** a copy of v0's `fixtures/flask-profile-api` and `contracts/profile-api/v1`. Add a `check.sh` that starts the service and runs the contract cases (reuse v0's runner logic in a self-contained script).
   - **`evals/repos/e2-bloated-python-service/`:**
     - A small Flask or FastAPI service with 2–3 endpoints and pytest tests.
     - A deliberately bad Dockerfile: `FROM python:3.8` (full image), `apt-get update` without cleanup, no multi-stage build, the whole context copied before the dependency install, running as root, no `.dockerignore`.
   - **`evals/repos/e3-bloated-node-service/`:** a similar Express service with a similarly bloated Dockerfile (`FROM node:18`, full image). It is the tool-reuse target, because the problems are similar across ecosystems.
2. **Baselines:** `evals/baseline.py` measures, for E2 and E3:
   - image size, from a host `docker build`, then `docker save` to a tarball;
   - trivy CVE counts by severity, via `docker run --rm` of the pinned `aquasec/trivy` image on the tarball (docker-archive format);
   - dive efficiency and wasted bytes, via the pinned `wagoodman/dive` image in CI mode on the tarball;
   - hadolint findings, via the pinned `hadolint/hadolint` image.

   Write the results to `evals/baselines.json` and commit them.
   - Pin images by tag and digest.
   - Name containers `pp-test-e-*` and clean them up.
   - If a pull is blocked by an approval prompt, report it.
3. **`evals/client.py`:** a small httpx client for the API contract (create a run, get a run, poll events).
4. **`evals/scenarios.py`:** `run_scenario(client, repo_url, goal, timeout_s)` waits for a terminal status and returns a metrics dict built from events and steps:
   - steps done and failed;
   - tokens per step;
   - `tool_schema_tokens` per step;
   - tools created (`tool_created`) and tools reused (a pick whose `provenance.run_id` is a different run);
   - CLI installs and refusals;
   - compactions;
   - lessons and gotchas recorded.
5. **`evals/assertions.py`:** checks for Sync 2, 3 and 4 (MVP_PLAN §7) that take metrics dicts and return a list of failures.
   - Sync 3 compares two runs: tool created in run 1, reused in run 2, with no new tool of the same purpose.
6. **`evals/chaos.py`:** starts the worker as a subprocess (`uv run portpilot worker`; the command will exist after Lane P), waits for `step_started` with `seq >= 2`, sends SIGKILL, restarts the worker, and asserts the Sync 4 conditions.
7. **`evals/README.md`:**
   - how to publish the three repos to GitHub under the user's account (`gh repo create ... --public --source ...`);
   - how to run each scenario.

   Don't publish anything yourself.

## Tests

`tests/evals/`:
- the scenario metric extraction and the assertions, against a synthetic event stream through `httpx.MockTransport`;
- the fixture repos' own test suites pass locally (`pytest` for E1 and E2, `npm test` for E3; pin its dev dependencies).

## Done

- `evals/baselines.json` is recorded and shows real problems in E2 and E3: CRITICAL or HIGH CVEs, large size, hadolint warnings.
- `uv run pytest tests/evals` is green.
- The fixture repo tests pass.
- Ruff is clean.
- Everything is committed on `mvp/e`.

## Stop conditions

- **Time box:** about 2 hours.
