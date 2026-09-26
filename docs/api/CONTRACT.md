# PortPilot MVP HTTP API contract (frozen; owner: Lead)

This contract is shared by Lane P (the FastAPI server) and Lane F (the Next.js client). Change it only through the Lead.

## Conventions

- **Base path:** `/api`. Every body is JSON unless noted.
- **Auth:** every route except `GET /api/health` requires `Authorization: Bearer <PORTPILOT_API_TOKEN>`. A missing or wrong token returns `401`.
- **Datetimes:** ISO 8601 strings with an offset, for example `2026-09-26T18:20:00+00:00`.
- **Models:** documents are the `to_doc()` shape of the dataclasses in `src/portpilot/core/models.py`, with datetimes converted to strings. Field names are exactly the dataclass field names, in snake_case.
- **Errors:** `{"error": {"code": "<snake_case>", "message": "<human text>"}}`.

| Status | Codes it covers |
|---|---|
| 400 | `bad_request` |
| 401 | `unauthorized` |
| 404 | `not_found` |
| 409 | `conflict`, for example resuming a completed run |
| 422 | `invalid_repo_url`, `invalid_goal` |
| 429 | `rate_limited` |

## Endpoints

| Method and path | Request | 2xx response |
|---|---|---|
| `GET /api/health` | none | `{"ok": true, "version": "0.1.0"}` |
| `POST /api/runs` | `{"repo_url": str, "goal": str, "budgets"?: Budgets}` | `201 {"run_id": str}` |
| `GET /api/runs?limit=50` | none | `{"runs": [RunSummary]}`, newest first |
| `GET /api/runs/{run_id}` | none | `{"run": Run, "plan": LongTermPlan \| null, "steps": [ShortTermPlan]}` |
| `GET /api/runs/{run_id}/steps/{step_id}` | none | `{"step": ShortTermPlan}` |
| `GET /api/runs/{run_id}/events?after_seq=0&limit=200` | none | `{"events": [Event], "next_after_seq": int}` |
| `POST /api/runs/{run_id}/pause` | none | `{"ok": true, "status": RunStatus}` |
| `POST /api/runs/{run_id}/resume` | none | `{"ok": true, "status": RunStatus}` |
| `POST /api/runs/{run_id}/cancel` | none | `{"ok": true, "status": RunStatus}` |
| `GET /api/runs/{run_id}/artifacts` | none | `{"artifacts": [ArtifactMeta]}` |
| `GET /api/runs/{run_id}/artifacts/{artifact_id}` | none | `{"artifact": Artifact}` |
| `GET /api/runs/{run_id}/download` | none | `application/gzip`: a tar.gz of the workspace branch |
| `GET /api/tools?status=active` | none | `{"tools": [ToolSummary]}` |
| `GET /api/tools/{name}` | none | `{"name": str, "versions": [ToolRecord]}`, oldest first, including files and tests |
| `GET /api/knowledge/search?q=...&kinds=lesson,gotcha&mode=hybrid&limit=10` | none | `{"hits": [{"item": KnowledgeItem, "score": float, "via": "vector" \| "text" \| "both"}]}` |
| `GET /api/knowledge?kinds=gotcha&run_id=...&limit=100` | none | `{"items": [KnowledgeItem]}` |

### `POST /api/runs` validation

`repo_url` must match `^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?/?$`. When the dev-only flag `PORTPILOT_ALLOW_LOCAL_REPOS=1` is set, it may instead be an absolute path to a local directory.

`goal` must be 3–2000 characters.

### Pause, resume and cancel

- **Pause** sets `control="pause"`. The worker stops at the next tool boundary and sets `status="paused"`.
- **Resume** sets a paused run back to `status="queued"` with `control=null`, so a worker claims it.
- **Cancel** sets `control="cancel"`. The worker then sets `status="cancelled"`.

## Shapes

- **`RunSummary`:**
  - `run_id`, `repo_url`, `goal`, `status`, `created_at`, `updated_at`;
  - `steps_total`, `steps_done`, `current_step_title`;
  - `usage` (`Usage`).
- **`Event`:** `{"run_id", "seq", "ts", "type", "step_id", "payload"}`, where `type` is one of `core.models.EVENT_TYPES`.
- **`ArtifactMeta`:** `{"artifact_id", "run_id", "step_id", "kind", "name", "created_at"}`.
- **`Artifact`:** `ArtifactMeta` plus `content`.
- **`ToolSummary`:**
  - `name`, `version`, `status`, `description`, `when_to_use`, `tags`, `requires_cli`;
  - `stats`, `provenance`, `created_at`;
  - `versions_count`.

  It carries no files or tests.

## Event payloads the UI renders

The worker emits these exact keys. Payload keys not listed here may be present and should be ignored.

| type | payload |
|---|---|
| `run_created` | `{repo_url, goal}` |
| `survey_done` | `{languages: {lang: files}, files: int, dockerfiles: [str], artifact_id}` |
| `plan_created` / `plan_revised` | `{version, phases: [{id, title}], reason?}` |
| `step_planned` | `{step_id, seq, title, phase_id}` |
| `step_started` | `{seq, title, attempt}` |
| `tools_selected` | `{candidates: [{name, version, score}], picks: [{name, version, reason}], missing: [str], core_tools: [str], tool_schema_tokens: int}` |
| `tool_loaded` | `{name, version, reason}`, a mid-step load |
| `tool_call` | `{tool, args_preview}` |
| `tool_result` | `{tool, ok, seconds, preview, artifact_id?}` |
| `tool_error` | `{tool, error}` |
| `tool_created` | `{name, version, purpose}` |
| `tool_validated` | `{name, version, ok, checks: [{name, ok}]}` |
| `tool_promoted` | `{name, version, previous_active}` |
| `tool_rejected` | `{name, version, reason}` |
| `cli_checked` | `{installed: {name: version}, arch}` |
| `cli_installed` | `{name, version, already_installed}` |
| `cli_refused` | `{name, reason}` |
| `compaction` | `{tokens_before, tokens_after, messages_before, messages_after}` |
| `checkpoint` | `{step_id, commit_sha}` |
| `step_verified` | `{ok, checks: [{name, ok, exit_code}]}` |
| `step_failed` | `{reason, attempt}` |
| `lesson_recorded` / `gotcha_recorded` | `{item_id, title, merged: bool}` |
| `budget_exceeded` | `{budget, used, limit}` |
| `paused` / `resumed` / `cancelled` / `completed` / `failed` | `{reason?}` |
