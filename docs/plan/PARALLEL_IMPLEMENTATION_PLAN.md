# PortPilot: Parallel Implementation Plan

Companion to `docs/charter/PROJECT_CHARTER.md`. The charter says *what* to build. This document says *who builds what, in which order, and against which frozen interfaces*, so the lanes can work at the same time without waiting on one another.

## 1. What we are building (one paragraph)

A Python harness (Strands Agents + OpenRouter) that takes a small Flask "Profile Normalization API", generates a brand-new TypeScript/Hono port into an empty directory, runs a live source-vs-target contract suite, and records everything in MongoDB Atlas. Policy v1 deliberately does not require preserving legacy error behavior, so the port fails the `422` + nested-error cases. The harness diagnoses the failure, writes candidate policy v2 with a rationale, regenerates from scratch under v2, compares pass rates, and promotes v2 only when it improves with no regressions. A run can pause after diagnosis or candidate-policy creation and resume from its Atlas run ID without redoing source analysis.

The product is the harness loop and its evidence trail: generate, test, diagnose, improve policy, re-run, promote. The Flask service, the Hono output and the UI are supporting parts.

## 2. Parallelization strategy

Three rules make the parallel work possible:

1. Freeze the interfaces in the first 20 minutes (section 4). Lanes build against the frozen contracts, not against each other's code.
2. Replace every dependency with a stand-in until the real one lands:
   - `InMemoryStore` stands in for Atlas. It has the same interface as `AtlasStore`.
   - Two hand-written reference targets stand in for LLM generation: `hono-v1-miss` (fails the error cases) and `hono-good` (passes everything).
   - Recorded JSON fixtures of runs, results and policies stand in for the live harness, so the UI can be built early.
3. Keep the orchestrator deterministic and put the LLM inside it. A plain Python state machine walks the milestones. At each milestone it runs a Strands agent with only that milestone's tools and the active policy. This makes checkpointing, pause/resume and testing straightforward. Only `generate_target` needs to be creative; diagnosis and evaluation are deterministic code.

### Critical path

```
Interfaces frozen ─► Hono template + generate_target ─► first live v1 generation that
misses 422 ─► diagnose ─► v2 regenerate ─► evaluate/promote ─► demo rehearsal
```

Everything else (Atlas, pause/resume, UI, the Flask fixture itself) runs alongside this path. The largest schedule risk is the LLM producing an unreliable v1/v2 split, so Lane C starts on it at minute 20.

## 3. Repository layout (frozen at T+0:20)

```
fixtures/
  flask-profile-api/          # Lane A  – controlled legacy source (app.py, requirements)
  reference-targets/
    hono-v1-miss/             # Lane A  – hand-written stand-in: idiomatic 400 errors (fails)
    hono-good/                # Lane A  – hand-written stand-in: full parity (passes)
contracts/
  profile-api/v1/cases.json   # Lane A  – 10 versioned contract cases
templates/
  hono-empty/                 # Lane C  – empty Hono project (package.json, tsconfig, src/index.ts stub)
policies/
  flask-to-hono.v1.md         # Lane D  – seed policy v1
  flask-to-hono.v2.expected.md# Lane D  – reference for what v2 must add (test oracle, not injected)
src/portpilot/
  config.py                   # Lead   – env loading (MONGODB_URI, OPENROUTER_API_KEY, MODEL_ID)
  models.py                   # Lead   – frozen dataclasses/pydantic models (section 4)
  store/
    base.py                   # Lead   – Store protocol
    memory.py                 # Lane B – InMemoryStore
    atlas.py                  # Lane B – AtlasStore (pymongo)
  contracts/
    runner.py                 # Lane A – run cases against base URL(s), diff source vs target
    services.py               # Lane A – start/stop Flask + Hono processes, health check, ports
  harness/
    orchestrator.py           # Lane C – milestone state machine, pause/resume
    agent.py                  # Lane C – Strands Agent factory (OpenRouter via OpenAIModel)
    tools/                    # Lane C owns the tool wrappers; logic comes from the lanes below
      inspect_source.py       # Lane C
      generate_target.py      # Lane C
      run_contract_tests.py   # Lane C (thin wrapper over Lane A runner)
      diagnose_failure.py     # Lane D
      create_candidate_policy.py # Lane D
      evaluate_policy.py      # Lane D
      persist_checkpoint.py   # Lane B
  cli.py                      # Lane E – `portpilot run|pause|resume|status|policies`
  ui/                         # Lane E – optional thin web view over the store
runs/                         # gitignored – runs/<run_id>/attempt-<n>-policy-v<k>/target/
tests/                        # every lane – pytest, named after behavior
```

`.gitignore` gotcha: the stock Python template ignores `target/`, `lib/`, `build/` and `dist/`. Generated targets under `runs/` should be ignored, so that is fine. Do not name committed source directories `lib/` or `target/`, and add `runs/` and `node_modules/` explicitly.

## 4. Frozen interfaces (Lead writes these in 0:00–0:20; changes need a heads-up in team chat)

### 4.1 Contract case format: `contracts/profile-api/v1/cases.json`

```json
{
  "suite": "profile-api", "version": 1,
  "cases": [
    {
      "id": "normalize_coerces_numeric_strings",
      "category": "coercion",
      "request": {"method": "POST", "path": "/profiles/normalize",
                  "json": {"name": "Ada", "email": "ADA@X.IO ", "age": " 042 "}},
      "compare": ["status", "json"],
      "ignore_paths": []
    }
  ]
}
```

The runner calls the source and the target with the same request. A case passes only when status and JSON body match exactly after `ignore_paths` are removed. The source's own responses are also snapshotted to `contracts/profile-api/v1/golden.json`, so the suite can check the source against itself.

### 4.2 Fixture behavior (Lane A implements; everyone relies on it)

| # | Case id | Category | Source behavior |
|---|---|---|---|
| 1 | `normalize_happy_path` | success | 200, normalized profile |
| 2 | `normalize_coerces_numeric_strings` | coercion | `" 042 "` → `42`; `"4.5"` → `4` (truncate, legacy quirk) |
| 3 | `normalize_applies_defaults` | defaults | missing `country` → `"US"`, `newsletter` → `false`, `tags` → `[]` |
| 4 | `normalize_trims_and_lowercases_email` | transform | `" ADA@X.IO "` → `"ada@x.io"` |
| 5 | `normalize_rejects_invalid_payload_with_422` | error-status | 422, nested error |
| 6 | `validate_accepts_valid_payload` | success | 200 `{"valid": true, "errors": []}` |
| 7 | `validate_missing_required_field_returns_422` | error-schema | 422, nested error, `field: "email"` |
| 8 | `validate_uncoercible_age_returns_422` | error-schema | 422, `issue: "not_coercible"` |
| 9 | `get_profile_found` | success | 200, seeded profile `p_001` |
| 10 | `get_profile_not_found_returns_nested_404` | error-schema | 404, nested error |

Nested error schema (the behavior v1 is designed to miss):

```json
{"error": {"code": "VALIDATION_FAILED", "message": "Invalid profile payload",
           "details": [{"field": "age", "issue": "not_coercible"}]}}
```

Expected v1 result: cases 5, 7, 8 and 10 fail (6/10), because idiomatic Hono/zod returns 400 with a flat body. Expected v2 result: 10/10. The demo depends on this split, so Lane D tests for it explicitly.

### 4.3 Core models: `src/portpilot/models.py`

```python
Milestone = Literal["source_analysis", "generation", "test", "diagnosis",
                    "candidate_policy", "regeneration", "retest",
                    "evaluation", "completion"]
RunStatus = Literal["running", "paused", "completed", "failed"]

@dataclass
class CaseResult:      # one contract case
    case_id: str; category: str; passed: bool
    source: dict; target: dict        # {"status": int, "json": Any}
    diff: list[str]                   # human-readable mismatches

@dataclass
class ContractResult:  # one full suite execution
    run_id: str; attempt: int; policy_version: int
    passed: int; total: int; cases: list[CaseResult]

@dataclass
class Diagnosis:
    run_id: str; attempt: int
    categories: list[str]             # e.g. ["error_status_and_schema"]
    failed_case_ids: list[str]; rationale: str

@dataclass
class Policy:
    name: str; version: int           # name = "flask-to-hono"
    status: Literal["active", "candidate", "retired", "rejected"]
    body: str                         # markdown instructions injected into generation
    rules: list[str]; parent_version: int | None; rationale: str | None
```

### 4.4 Store protocol: `src/portpilot/store/base.py`

```python
class Store(Protocol):
    def create_run(self, source_path: str, policy_version: int) -> str: ...
    def get_run(self, run_id: str) -> dict: ...
    def update_run(self, run_id: str, **fields) -> None: ...          # status, current_milestone, ...
    def start_milestone(self, run_id: str, name: Milestone, attempt: int) -> None: ...
    def complete_milestone(self, run_id: str, name: Milestone, attempt: int, artifact_ids: list[str]) -> None: ...
    def completed_milestones(self, run_id: str) -> list[tuple[Milestone, int]]: ...
    def put_artifact(self, run_id: str, kind: str, attempt: int, content: dict) -> str: ...
    def get_artifact(self, artifact_id: str) -> dict: ...
    def latest_artifact(self, run_id: str, kind: str) -> dict | None: ...
    def get_policy(self, name: str, version: int | None = None) -> Policy: ...  # None = active
    def save_policy(self, policy: Policy) -> None: ...
    def set_policy_status(self, name: str, version: int, status: str, decision: dict) -> None: ...
    def log_event(self, run_id: str, type: str, milestone: str, payload: dict) -> None: ...
    def events(self, run_id: str) -> list[dict]: ...
```

Atlas collections (the charter's names): `migration_runs`, `milestones`, `artifacts`, `policies`, `events`. Artifact `kind` values: `source_analysis`, `target_version` (file manifest + content hashes + path), `test_output` (`ContractResult`), `diagnosis`, `candidate_policy`, `evaluation`.

### 4.4a Additions made while scaffolding (T+0:20, now frozen too)

- `Store.list_policies(name) -> list[Policy]` (ascending), for `portpilot policies` and the v1-vs-v2 view.
- `Store.artifacts(run_id, kind=None, attempt=None) -> list[dict]` (ascending), so `evaluate_policy` can fetch a specific attempt's `test_output`.
- Cross-lane entry points: Lane A exposes `portpilot.contracts.cli.contracts_command(source_only, target) -> int`; Lane B exposes `portpilot.store.seed.seed_policy(store, path) -> Policy`. Lane E's `cli.py` calls both through lazy imports.
- Store conventions: run ids are `run_<12 hex>`; returned docs are plain dicts with no Mongo `_id`; timestamps are timezone-aware UTC `datetime`s.
- `models.Decision`: the typed return of `evaluate_policy` (baseline/candidate passed counts, `regressions`, `fixed`, `promoted`, `reason`). `Policy` gained an optional `decision` field.
- `harness/context.py`: `bind(store)` / `ctx()`. Tools keep the exact 4.5 signatures and get the store from here. Tests call `bind(InMemoryStore())`.
- `cases.json` cases carry `expect_status` (source-only sanity check). Full fixture behavior, error ordering and messages are in `contracts/profile-api/v1/SPEC.md`.
- Each Lane D tool file exposes a pure function (`diagnose`, `build_candidate`, `decide`) alongside the `@tool` wrapper, so the policy loop is testable without a store or LLM.

### 4.5 Tool signatures (Strands `@tool` functions; Lane C wires them, owning lanes implement the logic)

| Tool | Signature | Milestones that receive it |
|---|---|---|
| `inspect_source` | `(run_id) -> source_analysis artifact id` | source_analysis |
| `generate_target` | `(run_id, attempt, policy_version) -> target_version artifact id` | generation, regeneration |
| `run_contract_tests` | `(run_id, attempt) -> ContractResult` | test, retest |
| `diagnose_failure` | `(run_id, attempt) -> Diagnosis` | diagnosis |
| `create_candidate_policy` | `(run_id, diagnosis_id) -> Policy (candidate)` | candidate_policy |
| `evaluate_policy` | `(run_id, baseline_attempt, candidate_attempt) -> decision` | evaluation |
| `persist_checkpoint` | `(run_id, milestone, note) -> None` | all |

Promotion rule, implemented in `evaluate_policy` and never delegated to the LLM: promote only if `candidate.passed > baseline.passed` **and** every case that passed under the baseline also passes under the candidate. Otherwise the candidate is marked `rejected` and v1 stays `active`.

### 4.6 CLI surface (so the UI and the demo script can be written early)

```
portpilot run [--policy v1] [--pause-after diagnosis|candidate_policy]   # prints run_id
portpilot resume <run_id>
portpilot status <run_id>            # milestone, attempts, pass rates
portpilot policies                   # v1/v2, status, evaluation evidence
portpilot contracts --source-only    # source passes its own suite
```

## 5. Lanes

Each lane gets its own branch and worktree (`git worktree add ../portPilot-<lane> -b lane/<lane>`), and each lane can be one person, one AI agent, or a person driving an agent. File ownership follows section 3. A lane edits only its own files and asks the owner before touching anything else.

### Lead / Integrator (0:00–0:20, then integration + demo)
- Repo skeleton, `pyproject.toml` (uv, Python 3.12 pinned; the machine default is 3.14, which is riskier for SDK wheels), `.env.example`, `models.py`, `store/base.py`, empty tool stubs that raise `NotImplementedError`, and `cases.json` ids.
- Smoke tests, run at the same time as the skeleton:
  - Atlas: read/write one document.
  - Strands + OpenRouter: one tool call through `OpenAIModel(client_args={"api_key": ..., "base_url": "https://openrouter.ai/api/v1"}, model_id=...)`. Pick the model here. If tool calling is flaky, switch models now, not at hour 2.
- After T+0:20: merge lanes at each sync point, own `README.md` commands, run the demo script.

### Lane A: Source fixture + contract runner (Python)
1. Flask app with the 10 behaviors from 4.2, plus an in-memory seed `p_001`.
2. `services.py`: start Flask on `:5001` and a Hono target dir on `:8787` (`npx tsx src/index.ts`), poll a health endpoint, tear down cleanly, use a free port per attempt.
3. `runner.py`: execute cases, diff, return `ContractResult`, pretty print.
4. `hono-v1-miss` and `hono-good` reference targets, written by hand. They unblock Lanes C, D and E before any LLM output exists.
- Done: `portpilot contracts --source-only` gives 10/10; runner vs `hono-v1-miss` gives 6/10; runner vs `hono-good` gives 10/10.

### Lane B: Atlas persistence + checkpoints (Python)
1. `InMemoryStore` first, delivered by T+0:40 so the other lanes can use it.
2. `AtlasStore` (pymongo) with indexes on `run_id`, `(name, version)` unique on policies, and `(run_id, ts)` on events.
3. Seed policy v1 from `policies/flask-to-hono.v1.md` (`portpilot seed`).
4. `persist_checkpoint` tool and `completed_milestones` semantics for resume.
- Done: a shared pytest suite runs against both stores (parametrized fixture); killing the process and re-reading the run from Atlas returns the same milestone, artifacts and active policy.

### Lane C: Harness, generation, orchestrator (Python + Strands) — critical path
1. `templates/hono-empty` with `node_modules` installed once. Each target dir symlinks `node_modules` to the template, so there is no `npm install` per attempt (it is too slow for the demo loop).
2. `agent.py`: the per-milestone agent factory. Each milestone gets its own tool list and the active policy body in the system prompt.
3. `inspect_source`: reads `fixtures/flask-profile-api/` and produces a structured analysis (routes, fields, coercions, defaults, error handling). Stored as an artifact and never recomputed on resume.
4. `generate_target`: copy the template into a fresh `runs/<id>/attempt-n-policy-vk/target/`, ask the LLM for a JSON file map constrained to `src/**`, write it, run `tsc --noEmit`, and allow one repair retry on compile error. Store a manifest and hashes as a `target_version` artifact.
5. `orchestrator.py`: the milestone loop in 4.3 order. It skips `completed_milestones`, checkpoints after each milestone, and honors `--pause-after` by setting `status=paused` and exiting 0.
- Develop against `InMemoryStore` and the reference targets until Lanes A and B land.
- Done: `portpilot run` generates a fresh v1 target that boots and gets a `ContractResult`.
- Determinism guard: run the v1 generation 3 times at T+2:00. If v1 sometimes passes the 422 cases by accident, make the v1 policy more explicit about idiomatic framework defaults ("use `@hono/zod-validator` defaults for validation errors") rather than hard-coding a failure. Set temperature low.

### Lane D: Policy loop: diagnosis, candidate policy, evaluation (Python)
1. `policies/flask-to-hono.v1.md`: translate business logic faithfully, use idiomatic Hono validation. It says nothing about legacy status codes or error shape.
2. `diagnose_failure`: rule-based mapping from failed cases to categories. Status 422 vs 400, or a mismatch in `$.error.*`, maps to `error_status_and_schema`. Default and coercion mismatches map to their own categories (this keeps the second-category extension cheap).
3. `create_candidate_policy`: v1 body plus rule blocks keyed by category, with the rationale citing failed case ids and diffs. It is deterministic and template-driven. LLM drafting is a stretch goal. v2 is saved as `candidate`, with `parent_version=1`.
4. `evaluate_policy`: the promotion rule from 4.5. It writes an `evaluation` artifact and a promotion decision on both policy docs, and retires v1 to `retired` (kept for rollback) only on promotion.
- Build and test entirely against the reference targets: v1-miss result + good result must produce "promote", and the inverse must produce "reject".
- Done: `pytest tests/test_policy_loop.py` covers promote, reject and the no-regression veto.

### Lane E: Demo surface (CLI first, thin UI optional)
1. `cli.py` with Typer + Rich: milestone progress, a per-case pass/fail table, and a v1 vs v2 comparison table.
2. The same views read only from `Store`, so they work unchanged after a restart (this is the "refresh does not lose state" proof).
3. Optional, only if the CLI is done by T+3:15: a single-page read-only view (FastAPI on `127.0.0.1` + one HTML page polling `/runs/<id>`). No auth, local only. Say so in the README.
4. `docs/DEMO.md`: the exact 3-minute command script from the charter, including the pause → restart → resume beat.
- Build against recorded JSON fixtures from Lanes A and D until the harness produces real runs.

## 6. Timeline with parallel lanes

| Time | Lead | Lane A (fixture/runner) | Lane B (Atlas) | Lane C (harness) ★ | Lane D (policy) | Lane E (demo) |
|---|---|---|---|---|---|---|
| 0:00–0:20 | Skeleton, interfaces, both smoke tests | Draft 10 cases + error schema | Atlas cluster, URI, network access | OpenRouter key, model pick | Draft v1 policy text | Draft demo script |
| 0:20–1:00 | Review PRs, unblock | Flask app, runner, source 10/10 | InMemoryStore (by 0:40), AtlasStore | Hono template, agent factory, `inspect_source` | `diagnose_failure` on mock results | CLI skeleton on fixtures |
| **Sync 1 @ 1:00** | Merge A+B | Reference targets (6/10, 10/10) | Shared store tests green | | | |
| 1:00–1:40 | Wire runner → orchestrator | `services.py` process mgmt hardening | `persist_checkpoint`, seed policies | `generate_target` + compile check | `create_candidate_policy`, `evaluate_policy` | Status + results tables |
| **Sync 2 @ 1:40** | First end-to-end v1 on Atlas | | | Live v1 target gets tested | Loop tests green on reference targets | |
| 1:40–2:25 | Integrate D into orchestrator | Help C debug target boot issues | Resume semantics (`completed_milestones`) | Orchestrator milestones through `test` | Wire D tools into orchestrator | Policy comparison view |
| 2:25–3:05 | Determinism check (3× v1, 3× v2) | Add 2nd failure category (stretch) | Event log completeness | Regeneration under v2 | Promotion writes to Atlas | UI (optional) |
| **Sync 3 @ 3:05** | **Full v1→v2→promote on Atlas** | | | | | |
| 3:05–3:30 | Pause/resume demo beat | — | Verify reload after kill | `--pause-after`, resume skip proof | Rollback note on v1 | Resume view |
| 3:30–3:50 | Freeze main, README | Bug bash | Bug bash | Bug bash | Bug bash | Polish CLI output |
| 3:50–4:00 | Rehearse ×2, record | | | | | |

★ = critical path. Once Lane A or B finishes early, its owner pairs with Lane C, not with the UI.

### If you have fewer people
- 3 people: Lead+B (persistence is small), A+E (fixture, then CLI), C+D (the harness loop; D's logic is small and deterministic).
- 2 people: (Lead, A, B, E) and (C, D). Drop the web UI.
- With AI agents: give each lane's section of this document to one agent in its own worktree, with section 4 as a hard constraint and the lane's "Done" line as the stop condition. Keep Lane C human-supervised, since its prompt and determinism tuning need judgment.

## 7. Sync-point acceptance checks

| Sync | Command | Must show |
|---|---|---|
| 1 @ 1:00 | `portpilot contracts --source-only`; runner vs both reference targets | 10/10, 6/10, 10/10 |
| 2 @ 1:40 | `portpilot run --policy v1` (Atlas) | Fresh target boots; ContractResult + events in Atlas |
| 3 @ 3:05 | `portpilot run` end to end | v1 6/10 → v2 10/10, v2 `active`, v1 `retired`, evaluation artifact |
| Final | `portpilot run --pause-after candidate_policy`, kill, `portpilot resume <id>` | No second `source_analysis` milestone; completes; demo twice in a row |

## 8. Risks and pre-decided fallbacks

| Risk | Trigger | Fallback (decided now, not at hour 3) |
|---|---|---|
| OpenRouter tool calling flaky | Smoke test fails twice | Switch model. If it still fails, let the orchestrator call tool logic directly and use the LLM only for generation. |
| v1 doesn't reliably miss 422 | Determinism check at 2:25 | Tighten the v1 policy wording toward idiomatic defaults. Lower temperature. |
| v2 doesn't reliably hit 10/10 | Determinism check | Put the nested error schema example verbatim in the v2 rule block. Allow one compile/repair retry. |
| Generated target won't boot | Compile/boot error | One repair retry with the compiler output. The template pre-wires `@hono/node-server` so the LLM only writes routes. |
| Atlas slow/unavailable | Sync 1 | Keep running on InMemoryStore and switch back at Sync 3. Atlas is the stated system of record, so it must be live for the demo. |
| Demo-day LLM outage | Rehearsal | Show a recorded run from Atlas (the evidence is persisted). Never present reference targets as generated output. |

## 9. Merge discipline

- Short-lived branches `lane/<name>`, merged at the three sync points by the Lead. Before a sync, rebase and run `pytest` plus `portpilot contracts --source-only`.
- Section 4 changes only through the Lead, announced in team chat, and made in `models.py` / `store/base.py` first.
- Never commit `.env`, `runs/`, `node_modules/` or Atlas URIs. Reference targets and the Flask fixture are intentional fixtures and should be labeled that way in the README ("hackathon-authored" vs third-party, per the charter's success criteria).
