# Lane E brief: demo surface (CLI + Rich views + demo script)

Also read: charter sections E and F and "Three-minute demo"; plan section 4.6; `src/portpilot/store/__init__.py` (`get_store`); stub `src/portpilot/cli.py`; `harness/orchestrator.py` (signatures `start_run(store, policy_version, pause_after)` and `resume(store, run_id, pause_after)`).

You own: `src/portpilot/cli.py`, a new `src/portpilot/views.py`, `docs/DEMO.md`, `tests/test_cli*.py`, `tests/test_views*.py`, `tests/fixtures/demo/**`. Do not build the web UI.

## Deliverables

1. **`views.py`**: pure Rich renderers over plain data. They never touch a store.
   - `render_run_status(run, milestones, test_outputs)`:
     - run id and a colored status;
     - the current milestone;
     - a progress line over `models.MILESTONES` in order (done/current/pending, with attempt numbers);
     - per-attempt lines like `attempt 1 · policy v1 · 6/10`.
   - `render_contract_result(result: ContractResult)`: a table of case id | category | PASS/FAIL | first diff line, plus `passed/total`.
   - `render_policy_comparison(policies, baseline, candidate, decision)`:
     - policy versions with their status and a rationale excerpt;
     - a per-case v1 vs v2 table that marks fixed cases and regressions;
     - the decision and its reason.
   - `render_events(events, limit=20)`: a compact timeline.
2. **`cli.py`**: keep the existing command names and options and leave the `smoke` subcommands untouched.
   - Get the store from `get_store()`. Data fetching uses only Store protocol methods.
   - `run --policy vN --pause-after X`:
     - validate `X` against `models.PAUSABLE_MILESTONES` and the policy against `v<int>`;
     - lazy-call `orchestrator.start_run(...)`;
     - print the run id prominently; if the run paused, add the hint `portpilot resume <run_id>`;
     - render the status.
   - `resume <run_id>` and `status <run_id>`.
   - `policies [--run <run_id>]`: without `--run`, just list the policies; with it, show the comparison from that run's test outputs and evaluation.
   - Add an `events <run_id>` command.
   - `contracts --source-only | --target DIR`: lazy-import `portpilot.contracts.cli.contracts_command(source_only, target) -> int` (Lane A) and exit with its return code.
   - `seed`: lazy-import `portpilot.store.seed.seed_policy(store, POLICIES_DIR / "flask-to-hono.v1.md")` (Lane B).
   - Errors:
     - `NotFound` → a clean red error and exit 1;
     - `NotImplementedError`/`ImportError` from lanes not merged yet → "not implemented yet (lane X)" and exit 2, with no traceback.
3. **`tests/fixtures/demo/*.json`**: recorded data using the real case ids from `cases.json` and realistic bodies per SPEC.md.
   - The completed run:
     - attempt 1 under v1 at 6/10, failing cases 5, 7, 8 and 10 (source 422/404 nested vs target 400/404 flat);
     - the diagnosis and the candidate v2;
     - attempt 2 under v2 at 10/10;
     - the evaluation with `promoted=True`, v2 `active`, v1 `retired`;
     - about 15 events.
   - A paused-run variant that stopped after `candidate_policy`.
4. **Tests**:
   - Renderers: render with `Console(record=True, width=120)` and check the `export_text()` output.
   - CLI: `typer.testing.CliRunner`, with a monkeypatched `get_store` that returns a test-only `FakeStore` loaded from the fixtures, and monkeypatched orchestrator functions.
   - Cover an invalid `--pause-after`, `NotFound`, and the not-implemented path.
5. **`docs/DEMO.md`**: the exact 3-minute command script covering the charter's 8 beats:
   - `run --pause-after candidate_policy`, then kill/restart the process;
   - `resume <run_id>`;
   - `policies --run <run_id>`;
   - which Atlas collections to open.
   Note that the web UI is optional and not built.

`uv run portpilot --help` must work. In the report, paste a sample of the rendered status and policy-comparison output.
