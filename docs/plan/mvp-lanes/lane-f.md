# Lane F: Frontend (Next.js, deployed on Vercel)

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-f`, on branch `mvp/f`.
- **Wave:** 1.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` §1.1, §3.9 and §8 (Lane F);
  - `docs/api/CONTRACT.md`, which is frozen and is your single source of truth for data;
  - `src/portpilot/core/models.py`, for the field names.

## Owns

- `web/` (new): a standalone Next.js project, which becomes the Vercel project root.
- Nothing else. Don't touch Python.

## Stack

- The current stable Next.js with the App Router, TypeScript in strict mode, React, and ESLint (the Next config).
- Styling is plain CSS modules. No UI framework.
- **Pinned dependencies:** install with `npm install --save-exact` and commit `package-lock.json`.
- **Tests:** Vitest plus Testing Library, pinned.
- Node v26 is installed. Add `"engines"` to `package.json`.

## Build

1. **Typed client:** `web/lib/types.ts` defines TypeScript types for every shape in `CONTRACT.md`. `web/lib/api.ts` is a server-only client.
2. **API proxy:**
   - `web/app/api/pp/[...path]/route.ts` forwards to `PORTPILOT_API_URL` with `Authorization: Bearer ${PORTPILOT_API_TOKEN}`.
   - Both are server-side environment variables and are never exposed to the browser, so never prefix them `NEXT_PUBLIC_`.
   - It allows only `GET`s on the contract paths, plus `POST` on `runs`, `runs/*/pause`, `runs/*/resume` and `runs/*/cancel`. It streams the download.
3. **Fixtures mode:**
   - When `PORTPILOT_API_URL` is unset, the proxy serves `web/fixtures/*.json` instead. Write realistic fixtures that exercise every event type and payload in `CONTRACT.md`, including:
     - a completed run with 5 steps;
     - a running run;
     - a tool reused from another run.
   - `POST /runs` in fixtures mode returns the id of the running fixture.
4. **Access gate:**
   - `web/middleware.ts` requires a cookie set by `/login`, a passcode form checked against `PORTPILOT_UI_PASSCODE` with a constant-time compare.
   - The cookie is an HMAC of the passcode with `PORTPILOT_UI_SECRET`, `httpOnly`, `secure`, `sameSite=lax`.
   - In development, with no passcode configured, the gate is open and a banner says so.
5. **Pages** (client components poll every 2 s with `after_seq` while the run is not terminal):
   - **`/`:** a new-run form (repo URL with client-side regex validation, a goal with presets "Port Flask service to TypeScript/Hono" and "Optimize the Dockerfile (size, CVEs, layers)"), plus a recent-runs list.
   - **`/runs/[id]`:**
     - **Header:** status, repo, goal, usage; pause, resume and cancel buttons; a download link.
     - **Plan:** the LTP phases, each with its STP list and a status badge.
     - **Selected STP detail:** picked tools with their reasons, missing capabilities, tool-schema tokens, tokens used, acceptance check results, and commit SHA.
     - **Timeline:** the events, grouped by step and filterable by type, in an `aria-live="polite"` region.
     - **Environment panel:** CLI installs and refusals.
     - **Tools panel:** tools created, promoted and reused this run, each linking to `/tools/[name]`.
     - **Knowledge panel:** the lessons and gotchas this run recorded.
     - **Compaction:** a small visual of the before and after token counts.
   - **`/tools`** and **`/tools/[name]`:**
     - `/tools` is the library table: name, version, status, uses, failure rate, runs used in, and created-by run.
     - `/tools/[name]` shows the versions, with files and tests in read-only code blocks.
   - **`/knowledge`:** a search box, kind filters and a mode toggle (hybrid, vector, text), with result cards showing the score and `via`.
6. **Accessibility:**
   - Semantic landmarks, and a label on every control.
   - Keyboard reachable, with visible focus.
   - WCAG AA contrast.
   - Status is never shown by color alone.

## Tests

- Vitest unit tests for event grouping, metric derivation (created vs reused, compaction totals), the proxy allow-list, and the passcode HMAC check.
- A component test that renders the run page from the fixtures.

## Done

- In `web/`, `npm ci && npm run lint && npm test && npm run build` all pass.
- `npm run dev` in fixtures mode renders every page without console errors. Check each page with `curl` and look for the expected text.
- Everything is committed on `mvp/f`.
- Don't deploy to Vercel: that needs the user's account.

## Stop conditions

- **Contract gap:** if the contract is missing something the UI needs, report it. Don't invent endpoints.
- **Time box:** about 3 hours.
