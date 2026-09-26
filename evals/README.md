# PortPilot evals

Fixture repos, baseline measurements, and scenario/chaos scripts for the
MVP_PLAN §7 sync checks.

## Fixture repos (`repos/`)

- **`e1-flask-profile-api/`:** the profile-normalization Flask API and its
  contract cases. Standalone; run `./check.sh` to boot it and drive every
  case in `contracts/v1/cases.json`.
- **`e2-bloated-python-service/`:** a small Flask notes API with a
  deliberately bloated `Dockerfile` (old base image, no apt cleanup,
  single-stage, whole context copied before deps, runs as root).
- **`e3-bloated-node-service/`:** an Express bookmarks API with the same
  problem shape in its `Dockerfile`, on Node instead of Python -- the
  tool-reuse target for Sync 3.

Each repo has its own `README.md`, tests (`pytest` for E1/E2, `npm test` for
E3) and `Dockerfile`, and does not reference this repo.

### Publishing the fixture repos to GitHub

Not done by this eval suite -- run manually, under your own account, when
you want live repos for a real end-to-end run:

```bash
for repo in e1-flask-profile-api e2-bloated-python-service e3-bloated-node-service; do
  cd repos/$repo
  git init -q
  git add -A
  git commit -q -m "Initial commit"
  gh repo create "$repo" --public --source=. --remote=origin --push
  cd -
done
```

## Baselines (`baseline.py`)

Measures E2 and E3's Docker images: size (via `docker build` + `docker
save`), trivy CVE counts by severity, dive efficiency/wasted bytes, and
hadolint findings, using pinned scanner images (see the module docstring for
exact tag+digest). Writes `baselines.json`.

```bash
uv run python evals/baseline.py            # both E2 and E3
uv run python evals/baseline.py --repo e2   # just one
```

Containers are prefixed `pp-test-e-*` and removed when the script finishes
(built images too); if a scanner-image pull is blocked by an approval
prompt, the script reports the failed command and exits non-zero rather than
silently skipping the measurement.

## Running a scenario (`client.py`, `scenarios.py`)

```python
from evals.client import PortPilotClient
from evals.scenarios import run_scenario

with PortPilotClient("http://127.0.0.1:8000", token="...") as client:
    metrics = run_scenario(
        client,
        repo_url="https://github.com/<you>/e2-bloated-python-service",
        goal="Containerize this service with a small, secure image",
        timeout_s=1800,
    )
```

`metrics` is a dict of steps done/failed, tokens per step, tool-schema
tokens, tools created vs. reused, CLI installs/refusals, compactions, and
lessons/gotchas recorded -- see `scenarios.extract_metrics` for the exact
shape. Feed it to `evals/assertions.py`'s `check_sync2`/`check_sync3`
(two runs)/`check_sync4` to get the MVP_PLAN §7 pass/fail list.

## Chaos (`chaos.py`)

Starts the worker (`uv run portpilot worker`, from Lane P) as a subprocess,
waits for a `step_started` event with `seq >= 2` on a given run, `SIGKILL`s
it, restarts it, and returns the resumed run's metrics for `check_sync4`:

```bash
uv run python evals/chaos.py --token "$PORTPILOT_API_TOKEN" --run-id run_abc123
```

## Tests (`tests/evals/`)

Run against a synthetic event stream through `httpx.MockTransport` -- no
live API or Docker needed:

```bash
uv run pytest tests/evals
```
