# flask-to-hono v1

Purpose: port the Flask Profile Normalization API to an idiomatic, modern Hono (TypeScript) service that preserves the business logic — routing, field coercion, truncation, defaults, trimming/lowercasing, and seed data — while using the framework's own conventions for structure and validation.

## Rules
- Write only under `src/`. The entry point is `src/index.ts`; start the server with `@hono/node-server`'s `serve` on `process.env.PORT` bound to hostname `127.0.0.1`.
- Expose `GET /health` returning `{"ok": true}`.
- Expose `POST /profiles/normalize`, `POST /profiles/validate`, and `GET /profiles/:id`.
- Validate request bodies with zod through `@hono/zod-validator`, and rely on the framework's default validation error responses; return idiomatic JSON errors.
- The normalized profile always has all six keys: `name`, `email`, `age`, `country`, `newsletter`, `tags`.
- `name`: required string; trim it; a value that is empty after trimming counts as missing.
- `email`: required string; trim it and lowercase it; it must contain `@`.
- `age`: required; accept an integer as-is; truncate a float toward zero; accept a numeric string by trimming it, parsing it as an int or a float, and truncating (`" 042 "` becomes `42`, `"4.5"` becomes `4`); booleans are not coercible; the result must be in the range `0..150`.
- `country`: optional string, used as given; default `"US"` when absent.
- `newsletter`: optional boolean; default `false` when absent.
- `tags`: optional list of strings; default `[]` when absent.
- `POST /profiles/validate` applies the same field rules as `normalize`; on success it returns `{"valid": true, "errors": []}`.
- `GET /profiles/:id` returns the stored profile; seed one profile in memory at startup: `{"id": "p_001", "name": "Ada Lovelace", "email": "ada@example.com", "age": 36, "country": "GB", "newsletter": true, "tags": ["math", "computing"]}`.
