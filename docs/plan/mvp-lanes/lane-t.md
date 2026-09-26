# Lane T: Tool library and agent-written tools

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-t`, on branch `mvp/t`.
- **Wave:** 2.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` §3.2, §3.3 and §3.5;
  - `src/portpilot/core/{models,interfaces,fakes}.py`, which are frozen;
  - `docs/api/CONTRACT.md`, for the event payloads;
  - `docs/plan/mvp-lanes/lane-s.md`, for the frozen `pp_tool_run.py` runner protocol. Its code is in `src/portpilot/sandbox/runner/` on `main`.
  - Also look through `src/portpilot/knowledge/` (merged) and `src/portpilot/sandbox/` (merged), and `docs/spikes/S2_STRANDS.md` §1, which covers the `AgentTool` subclass and `register_dynamic_tool`.

## Owns

- `src/portpilot/toollib/` (new package).
- `tests/toollib/`.

## Conventions (frozen by this brief)

- **Tool names:** `^[a-z][a-z0-9_]{2,47}$`.
- **Code layout:**
  - A tool's code is `files["main.py"]`, which defines `run(params: dict) -> dict` using only the standard library plus CLIs listed in `requires_cli`.
  - Tests are `tests["test_main.py"]` (pytest). They import `main` from the tool directory, which is on `sys.path`.
- **Examples:** `input_schema` must contain `"examples": [ {...} ]`, with at least one example. The first example drives the smoke call.
- **Where a tool lives in the sandbox:** `/workspace/.pp/tools/<name>/<version>/`, holding `main.py` and a `tests/` directory.
- **Events:** the library emits them through an injected `event_sink(run_id, type, payload)`, which may be `None`. Types and payloads: `tool_created`, `tool_validated`, `tool_promoted`, `tool_rejected`, `tool_deprecated`, following `CONTRACT.md`.

## Build

### 1. `library.py`

`SandboxToolLibrary(tool_store, knowledge, sandbox, installer=None, event_sink=None, runner_path="/opt/pp/bin/pp_tool_run.py")` implements `core.interfaces.ToolLibrary`.

**`propose`:**
- Validates the name and both schemas (`jsonschema` `Draft202012Validator.check_schema`, plus an `examples` check).
- Sets `version = next_version`, `status = candidate` and the provenance.
- Saves the record and emits `tool_created`.

**`validate`:** writes the files into the run's sandbox, then runs the checks, recorded as `ValidationReport.checks`:
1. `py_compile`;
2. a forbidden-import scan that rejects `socket` servers, `ctypes` and `subprocess` with `shell=True`, and warns on network use;
3. pytest on the tool's tests;
4. the smoke call through the runner with `examples[0]`;
5. the result checked against `output_schema`.

It installs `requires_cli` through the installer first. It emits `tool_validated`.

**`promote`:**
- Requires a passing validation.
- **No-regression rule:** when an active version exists, its tests must also pass against the new `main.py`.
- **On success:**
  - The new version becomes `active` and the old one `deprecated`; it's kept for rollback.
  - The tool card is upserted into knowledge: `KnowledgeItem(id=f"tool_{name}", kind="tool_card", ref=f"tool:{name}@{version}", title=name, body=description + when_to_use, tags, facets)`.
  - Emits `tool_promoted`.
- **Otherwise:** the new version is `rejected`, and `tool_rejected` is emitted with the reason.

**`candidates`:**
- A hybrid `knowledge.search` with `kinds=["tool_card"]` and `status: active` merged into the filters.
- Adds the built-in selectable tools from `builtins.py`.
- Joins stats from `tool_store`, and returns `ToolCard`s ranked by score.

**`as_agent_tool`:** returns `SandboxScriptTool(AgentTool)`:
- **Spec:** name, description (`description` plus "When to use: …"), and `inputSchema={"json": input_schema}` with `examples` removed.
- **`stream`:**
  1. Write the files if they're missing, which is idempotent.
  2. Run `python3 <runner> --dir … --timeout N` with the params JSON on stdin, using `sandbox.exec`.
  3. Parse the single JSON line.
  4. Yield a Strands ToolResult: `status` success or error, with the JSON content.
  5. Call `record_use(ok)`.
- **`runner_path`:** the default is the image path. For `LocalSandboxManager` tests, copy the runner script from `src/portpilot/sandbox/runner/pp_tool_run.py` into the local workspace and point `runner_path` at it.

**`record_use` and deprecation:** when `uses >= 4` and `failure_rate > 0.5`:
- set the status to `deprecated`;
- emit `tool_deprecated`;
- upsert a gotcha into knowledge explaining why.

### 2. `builtins.py`

Built-in selectable tools are host-side and trusted. Each has a `ToolCard` with `builtin=True` and a factory `make(deps_like) -> AgentTool`.

The first one is `build_image(context_dir, dockerfile, tag)`, which wraps `portpilot.sandbox.buildkit.build_image`. It returns `{tar_path, size_bytes, seconds}`, so trivy and dive can scan the tarball.

### 3. `toollib/seeds/`

Seed library tools are stored as `ToolRecord`s with `author="seed"`. `seed_library(library, run_id=None)` loads them idempotently and validates them in a sandbox before activating them.

The seeds are:
- **`http_contract_diff`:**
  - **Params:** `{source_base_url, target_base_url, cases: [{id, method, path, body?}]}`.
  - Calls both sides with `urllib`, then compares status and JSON.
  - **Returns:** `{passed, total, cases: [{id, passed, diff}]}`.
  - This is the v0 contract runner idea, simplified.
- **`detect_test_command`:** looks at the repo (`pyproject.toml`, `package.json`, `go.mod`, a Makefile) and returns candidate test, lint and build commands.

**Don't seed anything for Dockerfiles or images.** The demo requires the agent to write that tool itself.

### 4. `toolsmith.py`

```
make_author_tool(library, sandbox, model_factory, tool_store) -> Callable
```

The returned callable has the exact signature Lane A calls:

```
author_tool(run_id, step_id, name, purpose, requirements) -> {"ok", "name", "version", "reason"}
```

It runs a small, separate Strands Agent (the `executor` role model):
- **Tools:**
  - `sandbox_shell` and `sandbox_file_editor`, confined by the prompt and a guard to the draft directory `/workspace/.pp/drafts/<name>/` and read-only use of `/workspace/repo`;
  - `run_tool_tests()`, which runs a validation-like check on the draft;
  - `submit_tool(description, when_to_use, input_schema, output_schema, tags, requires_cli)`, which reads the draft files, then calls propose, validate and promote.
- **Budget:** at most 2 submit attempts and 25 turns.
- **The system prompt** carries the conventions above.

## Tests (`tests/toollib/`)

**Offline** (`LocalSandboxManager`, `InMemoryToolStore`, `InMemoryKnowledgeStore`):
- the full round trip propose → validate → promote, after which the card is searchable through `candidates`;
- a broken tool is rejected, whether the failure is its tests, a bad schema, or a smoke call that doesn't match the output schema;
- a v2 that breaks v1's tests is rejected, and v1 stays active;
- `SandboxScriptTool` works when called from a Strands `Agent` driven by a scripted fake model;
- deprecation after repeated failures;
- the seeds validate and activate;
- a test asserting that tool code is never imported into the host process (check `sys.modules` and the file access pattern).

**`docker` marker:** the same round trip with `DockerSandboxManager` and the real runner inside the `portpilot-sandbox:dev` image.

**`llm` marker, run once:** the toolsmith writes a real tool from `purpose="count lines of code per file extension in the repo"`, and the tool ends up active. Keep it cheap, and report the tokens used.

## Done

- `uv run pytest tests/toollib` is green offline.
- The `docker` tests are green.
- The `llm` test has passed once.
- A plain `uv run pytest` is green.
- Ruff is clean.
- Everything is committed on `mvp/t`.

## Stop conditions

- **Interface change needed:** stop and report it; don't edit `core/`.
- **Time box:** about 3 hours.
