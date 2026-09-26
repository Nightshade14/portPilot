# Profile API contract, v1

Behavior the Flask service (`app.py`) implements, exercised by `cases.json`.
`golden.json` snapshots the service's own answers for each case. `expect_status`
in each case is a sanity check; `check.sh` compares live responses against it.

## Endpoints

| Method | Path | Success |
|---|---|---|
| GET | `/health` | 200 `{"ok": true}` (used by the service manager, not a contract case) |
| POST | `/profiles/normalize` | 200, normalized profile object |
| POST | `/profiles/validate` | 200 `{"valid": true, "errors": []}` |
| GET | `/profiles/<id>` | 200, stored profile |

## Normalized profile

Output keys, always all present: `name`, `email`, `age`, `country`, `newsletter`, `tags`.

| Field | Required | Rule | Default |
|---|---|---|---|
| `name` | yes | string, trimmed; empty after trim counts as missing | — |
| `email` | yes | string, trimmed and lowercased; must contain `@` | — |
| `age` | yes | int as-is; float truncated toward zero; string trimmed, then parsed as int or float and truncated (`" 042 "` → `42`, `"4.5"` → `4`); booleans are not coercible; must be `0..150` | — |
| `country` | no | string, as given | `"US"` |
| `newsletter` | no | boolean | `false` |
| `tags` | no | list of strings | `[]` |

## Error schema (the legacy behavior policy v1 is designed to miss)

All validation failures return HTTP `422`. Unknown profile ids return `404`. Both use this nested body:

```json
{"error": {"code": "VALIDATION_FAILED", "message": "Invalid profile payload",
           "details": [{"field": "age", "issue": "not_coercible"}]}}
```

- `code`: `VALIDATION_FAILED` (422) or `NOT_FOUND` (404).
- `message`: `"Invalid profile payload"` (422) or `"Profile not found"` (404).
- `details`: one entry per failing field, in field order `name`, `email`, `age`, `country`, `newsletter`, `tags`. At most one issue per field, checked in the order listed below.
- `issue` values: `required`, `invalid_format` (email without `@`), `not_coercible`, `out_of_range`, `invalid_type` (wrong type for `name`, `email`, `country`, `newsletter`, `tags`).
- 404 details: `[{"field": "id", "issue": "not_found"}]`.
- A non-JSON or non-object body returns 422 with `details: [{"field": "body", "issue": "invalid_type"}]`.

`/profiles/validate` uses the same rules as `/normalize`; on failure it returns the same 422 error body, not `{"valid": false}`.

## Seed data

```json
{"id": "p_001", "name": "Ada Lovelace", "email": "ada@example.com", "age": 36,
 "country": "GB", "newsletter": true, "tags": ["math", "computing"]}
```
