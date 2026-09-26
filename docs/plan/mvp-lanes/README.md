# MVP lane and spike briefs

These are the task briefs for the subagents that implement `docs/plan/MVP_PLAN.md`.

Each brief is self-contained. A subagent works only in its own worktree (`../portPilot-spike-<n>` or `../portPilot-mvp-<lane>`) and edits only the paths its brief assigns.

## Rules for every subagent

- **Worktree:** pass your worktree path as `working_dir` on every shell call. Never edit the main checkout `/Users/satyamchatrola/codes/personal/portPilot`, except to read `.env`.
- **Python:** run it with `uv run` from your worktree. Pin exact versions for any new dependency, and add it with `uv add <pkg>==<ver>`.
- **Secrets:**
  - Load them only with `dotenv_values('/Users/satyamchatrola/codes/personal/portPilot/.env')`.
  - Never print, log, commit or copy secret values.
  - Redact any `mongodb(+srv)://…` string in output you show.
- **Docker:**
  - Prefix every container, network and volume you create with `pp-test-<your id>-`.
  - Remove them when you finish.
  - Never touch `portpilot-mongo` (the shared local Mongo on 127.0.0.1:27018) or `muybridge-livekit`.
- **Git:** commit locally on your branch, with a concise imperative message. Never push, force, or rewrite history.
- **Before you commit:** run `uv run ruff check` and `uv run ruff format --check` on the paths you touched, plus the tests for your area.
- **Your final message** must include:
  - status;
  - what you verified, with the commands you used;
  - what you could not verify;
  - the commit SHA(s);
  - open questions.
