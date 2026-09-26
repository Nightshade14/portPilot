# Lane briefs: shared rules

Every lane agent (human or AI) follows these, plus its own `lane-*.md` brief.

- Work only in your own worktree `../portPilot-lane-<x>` on branch `lane/<x>`. Use absolute paths.
- Read first: `AGENTS.md`; the plan (`docs/plan/PARALLEL_IMPLEMENTATION_PLAN.md`) sections 3 and 4 (including 4.4a) and your lane's section; `src/portpilot/models.py`; `src/portpilot/store/base.py`; your stub files.
- Frozen (never edit): `src/portpilot/models.py`, `src/portpilot/store/base.py`, `src/portpilot/config.py`, `src/portpilot/harness/context.py`, `contracts/profile-api/v1/cases.json`, `contracts/profile-api/v1/SPEC.md`, and every file another lane owns. Keep the `@tool` function names and signatures. If a frozen file has to change, stop and report it instead of editing it.
- Edit only the files your brief says you own.
- Other lanes are being built at the same time, so on your branch their code is still `NotImplementedError` stubs. Build against the frozen interfaces, and use test-only fakes or recorded fixtures where you need another lane's code.
- Artifact content conventions: `test_output` = `ContractResult.to_doc()`, `diagnosis` = `Diagnosis.to_doc()`, `candidate_policy` = `Policy.to_doc()`, `evaluation` = `Decision.to_doc()`. Policy name is `portpilot.config.POLICY_NAME`.
- Any server binds `127.0.0.1` only.
- Setup: run `uv sync` once. Before finishing, these must be clean: `uv run pytest`, `uv run ruff check src tests`, `uv run ruff format --check src tests`.
- Test names describe behavior, for example `test_get_policy_without_version_returns_active`.
- Scratch files go in `$KIROCREW_SCRATCH`.
- Commit to your lane branch with focused imperative subjects, staging specific files. Never push. Never touch `main`. No credentials are available or needed; skip live-Atlas/LLM tests when their env vars are unset.
- Stop when every deliverable passes, or when you are blocked on a frozen-interface issue.
- Report: status, commit list, files, exact test output, deviations and open questions.
