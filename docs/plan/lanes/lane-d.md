# Lane D brief: policy loop

Also read: charter section D; plan sections 2, 4.2 and 4.5; `contracts/profile-api/v1/SPEC.md`; `cases.json`; `src/portpilot/harness/context.py`; stubs `harness/tools/diagnose_failure.py`, `create_candidate_policy.py`, `evaluate_policy.py`.

You own: `policies/**`, those three tool files, `tests/test_policy_loop.py`, `tests/fixtures/policy_loop/**`.

## Deliverables

1. **`policies/flask-to-hono.v1.md`**: the seed policy that is injected into the code-generation agent's system prompt.
   - Format: `# flask-to-hono v1`, a purpose line, then `## Rules` with `- ` bullets (Lane B parses these bullets into `Policy.rules`).
   - Business logic: translate it faithfully from the source analysis (routes, coercion/truncation, defaults, trim/lowercase, seed data).
   - Idiomatic modern Hono: validate bodies with zod via `@hono/zod-validator`, rely on the framework's default validation error responses, and return idiomatic JSON errors.
   - It must not mention preserving legacy status codes or legacy error schemas. That is the rule v1 is designed to miss.
   - Target constraints: write only under `src/`. Entry point is `src/index.ts`, using `@hono/node-server` `serve` on `process.env.PORT` with hostname `127.0.0.1`. Expose `GET /health` → `{"ok": true}`.
2. **`policies/flask-to-hono.v2.expected.md`**: a test oracle only, never injected. It lists what a correct v2 must add.
3. **`diagnose(result) -> Diagnosis`**: pure and rule-based.
   - Classify each failed case from the `CaseResult.source`/`target` dicts, not from Lane A's exact diff wording:
     - source status ≥ 400 and (status differs, or the target json lacks the nested `error.code`/`error.details` shape) → `error_status_and_schema`;
     - else category `defaults` → `defaults`;
     - category `coercion` → `coercion`;
     - target has `error` (unreachable) → `target_unreachable`;
     - anything else → `behavior_mismatch`.
   - Categories are deduped and keep first-seen order.
   - The rationale cites each failed case id with its first diff line, or with the source/target status.
4. **`build_candidate(parent, diagnosis) -> Policy`**: a deterministic template.
   - Fields: `version = parent.version + 1`, `status="candidate"`, `parent_version=parent.version`.
   - Body: the parent body plus one `## Rule block: <category>` per category. `rules` is the parent's rules plus the new ones. `rationale` cites the case ids.
   - The `error_status_and_schema` block has to make an LLM reliably reach 10/10. It must state:
     - 422 for every validation failure and 404 for unknown ids, never 400;
     - the nested schema verbatim from SPEC.md, with the exact messages;
     - details ordering (name, email, age, country, newsletter, tags; one issue per field);
     - the issue codes, the 404 details, and the non-object-body case;
     - "validate manually or with a custom zod-validator hook; do not rely on default error responses".
   - Also include short blocks for `defaults`, `coercion` and `behavior_mismatch`.
5. **`decide(run_id, baseline, candidate) -> Decision`**: promote only if `candidate.passed > baseline.passed` and there are no regressions (`baseline.passed_ids - candidate.passed_ids` is empty). Fill `fixed`, `regressions`, the versions from `ContractResult.policy_version`, and a readable `reason`.
6. **`@tool` wrappers**, all using `ctx().store`:
   - `diagnose_failure(run_id, attempt)`:
     1. take `store.artifacts(run_id, "test_output", attempt)[-1]` and run `diagnose`;
     2. `put_artifact("diagnosis")`;
     3. `log_event("decision", "diagnosis", ...)`;
     4. return `{**diagnosis.to_doc(), "artifact_id": id}`.
   - `create_candidate_policy(run_id, diagnosis_id)`:
     1. load the diagnosis artifact; the parent is `get_policy(POLICY_NAME)` (the active one);
     2. run `build_candidate`, then `save_policy`;
     3. `put_artifact("candidate_policy")` and `log_event`;
     4. return the policy doc plus `artifact_id`.
   - `evaluate_policy(run_id, baseline_attempt, candidate_attempt)`:
     1. load both test outputs, run `decide`, and `put_artifact("evaluation")`;
     2. on promote: candidate → `active` and baseline → `retired` (kept for rollback), with the decision recorded on both;
     3. on reject: candidate → `rejected` with the decision; the baseline stays `active`;
     4. `log_event("decision", "evaluation", ...)` and return the decision doc plus `artifact_id`.

## Tests

- Build synthetic `ContractResult`s from `cases.json`:
  - v1-miss: cases 5, 7, 8 and 10 fail, with source 422/404 nested vs target 400/404 flat;
  - good: 10/10;
  - regressing: fixes those 4 but breaks `normalize_applies_defaults`.
- `diagnose` returns `["error_status_and_schema"]` with the 4 ids.
- The v2 text contains the verbatim schema and `422`. The v1 text contains neither `422` nor `VALIDATION_FAILED`.
- `decide`: miss→good promotes; good→miss rejects; a regression vetoes promotion.
- Wrappers end-to-end: use a test-only `FakeStore` (just the methods you call, matching the `store/base.py` semantics), bound with `bind()`. `InMemoryStore` is being built in parallel.

In the report, paste the full v1 policy text and the `error_status_and_schema` block.
