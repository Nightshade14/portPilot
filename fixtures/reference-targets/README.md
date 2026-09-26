# Reference targets

These two Hono/TypeScript services are **hackathon-authored test stand-ins**,
written by hand to unblock the harness lanes before any LLM generation exists.
They are **never** presented as generated output — the harness's real product is
the target it generates from a policy. These exist only so the contract runner,
the diagnosis loop, and the CLI can be built and tested against known-good and
known-failing targets.

- `hono-good/` — full behavioral parity with the Flask source. Passes 10/10.
- `hono-v1-miss/` — correct business logic (coercion, truncation, defaults,
  trim/lowercase, seed) but idiomatic zod/Hono error handling: a default-style
  400 with a flat body and a flat `{"error":"Not found"}` 404. It fails exactly
  the four legacy-error-schema cases and passes the other six (6/10), matching
  what policy v1 is designed to miss.

Each target reads `PORT` from the environment, binds `127.0.0.1` only, and
exposes `GET /health` returning `{"ok": true}`. Run with `npm install` then
`npx tsx src/index.ts`. `node_modules/` is gitignored; `package-lock.json` is
committed.
