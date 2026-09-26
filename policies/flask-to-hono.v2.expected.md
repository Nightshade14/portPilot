# flask-to-hono v2 (expected)

Test oracle only. This file is never injected into any agent; it records what a
correct candidate v2 policy must add on top of v1 so tests can assert the diff.

A correct v2 adds a `## Rule block: error_status_and_schema` that states:

- Return HTTP `422` for every validation failure and `404` for an unknown profile id. Never return `400`.
- Every error response uses this nested body verbatim:

```json
{"error": {"code": "VALIDATION_FAILED", "message": "Invalid profile payload",
           "details": [{"field": "age", "issue": "not_coercible"}]}}
```

- `code` is `VALIDATION_FAILED` for `422` and `NOT_FOUND` for `404`.
- `message` is `"Invalid profile payload"` for `422` and `"Profile not found"` for `404`.
- `details` carries one entry per failing field, in field order `name`, `email`, `age`, `country`, `newsletter`, `tags`, at most one issue per field.
- `issue` values are `required`, `invalid_format` (email without `@`), `not_coercible`, `out_of_range`, `invalid_type`.
- A `404` uses `details: [{"field": "id", "issue": "not_found"}]`.
- A non-JSON or non-object body returns `422` with `details: [{"field": "body", "issue": "invalid_type"}]`.
- Validate manually or with a custom zod-validator hook; do not rely on default error responses.

It must also add short rule blocks for `defaults`, `coercion`, and `behavior_mismatch`
when those categories are diagnosed.
