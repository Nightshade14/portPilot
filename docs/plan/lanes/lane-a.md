# Lane A brief: source fixture + contract runner

Also read: `contracts/profile-api/v1/SPEC.md` (authoritative fixture behavior), `cases.json`, `src/portpilot/config.py`, stubs `src/portpilot/contracts/runner.py` and `services.py`.

You own: `fixtures/flask-profile-api/**`, `fixtures/reference-targets/**`, `src/portpilot/contracts/**` (including a new `cli.py`), `contracts/profile-api/v1/golden.json`, `tests/test_contracts*.py`, `tests/test_fixture*.py`.

## Deliverables

1. `fixtures/flask-profile-api/app.py` (+ `requirements.txt` with `flask==3.1.3`). Implement SPEC.md exactly: `GET /health` → `{"ok": true}`, normalize, validate, get, the 422 nested errors (exact messages, detail ordering, issue codes), the nested 404, and seed `p_001`. Runnable as `python app.py --port N` on 127.0.0.1. Plain, readable Flask (~150 lines), because the harness reads it as the "legacy" source. Set `app.json.sort_keys = False`.
2. `services.py`:
   - `free_port()`.
   - `flask_source(port=None)`: context manager that starts the app via `sys.executable`, polls `/health` for up to ~10 s, then terminates and waits on exit. Yields the base URL.
   - `hono_target(target_dir, port=None)`: runs `npx tsx src/index.ts` with env `PORT`, polls health for ~20 s, and kills the process group on exit.
   - If boot fails, raise a clear error that includes the tail of stderr.
3. `runner.py`:
   - `call_case`: httpx, 5 s timeout. Returns `{"status","json"}`, or `{"error"}` if the service is unreachable.
   - `compare_case`: diffs each field in `compare` after removing dotted `ignore_paths` such as `error.message`. Diff lines read like `status: source=422 target=400` and `json.error.code: missing in target`.
   - `run_suite`.
   - `run_source_only`: checks `expect_status`, plus equality with `golden.json` when that file exists.
   - `snapshot_golden(source_url)`: writes `golden.json`. Generate it and commit it.
4. `src/portpilot/contracts/cli.py` with `contracts_command(source_only: bool, target: str | None) -> int`. It boots the services itself and prints a Rich table (case id, category, PASS/FAIL, first diff line) plus `passed/total`. Returns 0 when everything passes, else 1. Lane E's `cli.py` calls it; do not edit `cli.py`.
5. Hand-written reference targets in TypeScript/Hono. Add `fixtures/reference-targets/README.md` saying these are hackathon-authored test stand-ins and are never presented as generated output.
   - `hono-good/`: full parity, 10/10.
   - `hono-v1-miss/`: correct business logic (coercion, truncation, defaults, trim/lowercase, seed) with idiomatic zod/Hono errors: a default-style 400 with a flat body, and a flat 404 like `{"error":"Not found"}`. It must fail exactly `normalize_rejects_invalid_payload_with_422`, `validate_missing_required_field_returns_422`, `validate_uncoercible_age_returns_422` and `get_profile_not_found_returns_nested_404`, and pass the other 6.
   - Each target: `package.json` (`"type": "module"`, start script `tsx src/index.ts`) with exact versions:
     - deps: `hono 4.13.9`, `@hono/node-server 2.1.1`, `@hono/zod-validator 0.9.1`, `zod 4.6.5`;
     - devDeps: `tsx 4.23.15`, `typescript 5.9.3`, `@types/node 26.6.3`.
   - Also `tsconfig.json`, and `src/index.ts` reading `PORT`, binding 127.0.0.1, with `GET /health`.
   - Run `npm install` in each target. Commit `package-lock.json`; `node_modules` is gitignored. `npx tsc --noEmit` must pass.
6. Tests:
   - Unit tests for `compare_case` and `ignore_paths`.
   - Integration tests that assert: source-only 10/10, `hono-v1-miss` 6/10 with exactly those 4 failed ids, `hono-good` 10/10.
   - Skip the Node tests if `npx` is missing.

Report the actual 10/10, 6/10 and 10/10 results and any deviation from SPEC.md.
