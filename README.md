# PortPilot

Self-improving, MongoDB Atlas-backed harness that ports a Flask service to a fresh TypeScript/Hono service and proves behavior parity with contract tests. See `docs/charter/PROJECT_CHARTER.md` (what) and `docs/plan/PARALLEL_IMPLEMENTATION_PLAN.md` (who/when/interfaces).

## Setup

Requires `uv`, Python 3.12 (pinned in `.python-version`) and Node 20+.

```bash
uv sync                      # create .venv and install pinned deps
cp .env.example .env         # fill in MONGODB_URI, OPENROUTER_API_KEY, MODEL_ID
```

## Commands

| Command | Purpose |
|---|---|
| `uv run pytest` | Unit and interface tests (no network) |
| `PORTPILOT_TEST_MONGODB_URI=mongodb://127.0.0.1:27018/ uv run pytest` | Also run the Mongo-backed store and resume tests against a disposable local MongoDB (`docker run -d --name portpilot-mongo -p 127.0.0.1:27018:27017 mongo:8.2`). Each test uses and drops its own `portpilot_test_*` database. Kept separate from `MONGODB_URI` so tests never touch the Atlas cluster in `.env`. |
| `uv run ruff check src tests && uv run ruff format --check src tests` | Lint and format check |
| `uv run portpilot smoke atlas` | Write/read/delete one document in Atlas |
| `uv run portpilot smoke llm` | One Strands tool call through OpenRouter with `MODEL_ID` |
| `uv run portpilot --help` | CLI surface (plan 4.6); most commands are stubs until their lane lands |

## Layout

Owner per path is in plan section 3. Frozen interfaces: `src/portpilot/models.py`, `src/portpilot/store/base.py`, `src/portpilot/harness/tools/*` signatures, `contracts/profile-api/v1/cases.json` + `SPEC.md`. Change them only through the Lead.

`fixtures/` holds hackathon-authored fixtures (the Flask source and hand-written reference targets). Reference targets are test stand-ins and are never presented as generated output.
