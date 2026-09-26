# PortPilot — three-minute demo script

The exact command sequence for the live demo. It maps the charter's eight
"Three-minute demo" beats to concrete commands. All services bind `127.0.0.1`
only; MongoDB Atlas is the system of record. There is **no web UI** — the demo
is a clean terminal flow (the web view is optional and not built).

## Before you start (off camera)

```bash
uv sync                       # once
cp .env.example .env          # set MONGODB_URI, OPENROUTER_API_KEY, MODEL_ID
export PORTPILOT_STORE=atlas  # Atlas is the demo system of record
uv run portpilot smoke atlas  # expect: "Atlas OK: round-tripped one document"
uv run portpilot smoke llm    # expect: "LLM OK: ... called the tool once -> 42"
uv run portpilot seed         # seed policy v1 (flask-to-hono.v1.md) as active
```

## The 3-minute flow

### Beat 1 — the legacy source and its contract (0:00–0:20)

Show the Flask source and the 10 versioned contract cases.

```bash
sed -n '1,40p' fixtures/flask-profile-api/app.py
python -m json.tool contracts/profile-api/v1/cases.json | head -30
uv run portpilot contracts --source-only     # source passes its own suite: 10/10
```

### Beat 2 — start v1 and generate a target from an empty project (0:20–0:50)

Start a run and **pause after the candidate policy is written**, so we can prove
durable pause/resume on camera. Note the printed `run_id`.

```bash
uv run portpilot run --policy v1 --pause-after candidate_policy
# prints:  run started: run_XXXXXXXXXXXX
#          paused — resume with: portpilot resume run_XXXXXXXXXXXX
RUN=run_XXXXXXXXXXXX
```

### Beat 3 — run the tests, show the behavioral mismatch (0:50–1:15)

```bash
uv run portpilot status $RUN
# attempt 1 · policy v1 · 6/10   ← v1 misses the 422/404 error behavior
```

### Beat 4 — persisted failure evidence and current milestone in Atlas (1:15–1:35)

```bash
uv run portpilot events $RUN     # timeline: analysis -> generation -> test(6/10) -> diagnosis -> candidate_policy -> paused
```

Open these Atlas collections to show the evidence is durable, not in memory:
`migration_runs` (status `paused`, `current_milestone: candidate_policy`),
`milestones`, `artifacts` (the `test_output` and `diagnosis`), `events`.

### Beat 5 — pause, reload, resume from the Atlas checkpoint (1:35–2:05)

**Kill the process / close the terminal** to prove nothing is held in memory,
then resume using only the saved run id:

```bash
# (new shell)  export PORTPILOT_STORE=atlas
uv run portpilot resume run_XXXXXXXXXXXX
```

The run continues from `candidate_policy` — it does **not** re-run
`source_analysis`. Confirm in the events timeline that `source_analysis` appears
only once.

### Beat 6 — candidate policy v2 and its rationale (2:05–2:25)

```bash
uv run portpilot policies                    # v1 (retired), v2 (active) + rationale excerpts
```

### Beat 7 — regenerate the target from the original Flask source under v2 (2:25–2:40)

The resumed run regenerates from scratch under v2 into a fresh target directory.
Show the second attempt in status:

```bash
uv run portpilot status $RUN
# attempt 2 · policy v2 · 10/10
```

### Beat 8 — compare v1 vs v2, promote, show corrected behavior (2:40–3:00)

```bash
uv run portpilot policies --run $RUN
```

Expected rendered comparison:

```
decision: PROMOTED  v1 6/10 -> v2 10/10
```

with the per-case table marking `normalize_rejects_invalid_payload_with_422`,
`validate_missing_required_field_returns_422`,
`validate_uncoercible_age_returns_422` and
`get_profile_not_found_returns_nested_404` as **fixed**, and no regressions.
v2 is `active`, v1 is `retired` (kept for rollback).

## Notes

- Every command reads run state only from the Store, so a refresh or restart
  never loses run state, artifact references, test evidence, or the active
  policy — that is the "long-horizon" proof.
- While other lanes are still stubs, `run`, `resume`, `contracts` and `seed`
  print a friendly `not implemented yet (lane X)` and exit 2 (no traceback).
  Use the recorded fixtures under `tests/fixtures/demo/` to rehearse the CLI
  views before the live harness is wired end to end.
- The web UI is optional and was not built (charter: the interface is
  supporting evidence, not the product).
