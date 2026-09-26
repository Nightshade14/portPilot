# Lane A: Agent core (critical path)

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-mvp-a`, on branch `mvp/a`.
- **Wave:** 1, started late.
- **Read first:**
  - `docs/plan/MVP_PLAN.md` §3.1 and §3.3–3.7, all of them carefully;
  - `src/portpilot/core/{models,interfaces,fakes,config}.py`, which are frozen;
  - `docs/api/CONTRACT.md`, especially the event payload table: your events must match it exactly;
  - `docs/spikes/S2_STRANDS.md` and `spikes/s2/*.py`, which verified the Strands APIs you will use;
  - `docs/spikes/S3_SANDBOX.md`.

## Owns

- `src/portpilot/agent/` (new package).
- `tests/agent/`.

Other lanes build in parallel against the same `core/` interfaces:
- **M:** the Atlas stores, `AtlasSessionRepository` and `AtlasStorage`.
- **K:** `KnowledgeStore` and `render_markdown`.
- **S:** `DockerSandboxManager`, `CliInstaller` and `shell_guard`.
- **T (later):** `ToolLibrary` and the toolsmith.

**Don't import their packages.** They aren't on your branch. Depend only on `core/` interfaces, and on injected callables for anything else. The Lead wires the real implementations at integration.

## Verified Strands facts (1.57.1)

- **Loading a tool mid-run:** `agent.tool_registry.register_dynamic_tool(tool)`.
- **Guardrails:** `Agent(interventions=[...])`, using an `InterventionHandler.before_tool_call`.
- **Context window:** `OpenAIModel(client_args={...}, model_id=..., params={"temperature": ...}, context_window_limit=N)` takes `context_window_limit` as a top-level config setting. It is required for proactive compression.
- **Compaction:** `SummarizingConversationManager(summary_ratio, preserve_recent_messages, summarization_agent, pin_first=1, proactive_compression={"compression_threshold": 0.7})`.
- **Offloading large outputs:** `ContextOffloader` from `strands.vended_plugins.context_offloader`, taking a `Storage`.
- **Sessions:** `RepositorySessionManager(session_id=..., session_repository=...)` persists every message. A tool call cut off by `kill -9` is repaired automatically on the next `agent()` call.
- **Typed output:** `agent.structured_output(PydanticModel, prompt)`.
- **Sandbox tools:** `strands.sandbox.docker.DockerSandbox(...).get_tools()` provides `sandbox_shell` and `sandbox_file_editor`.
  - For a generic `Sandbox`, including `NotASandboxLocalEnvironment` from `LocalSandboxManager.sandbox()`, check the source for how to obtain the same two tools, for example `make_shell` / `make_file_editor`.
- **Models:**
  - executor and planner: `settings.model_id` (`anthropic/claude-sonnet-4.5`);
  - side tasks: `settings.model_id_aux` (`google/gemini-2.5-flash-lite`).

## Build

### 1. `agent/deps.py`

`AgentDeps` is a dataclass:
- `run_store: RunStore`, `tool_store: ToolStore`;
- `knowledge: KnowledgeStore`;
- `sandbox: SandboxManager`, `installer: CliInstaller`;
- `tool_library: ToolLibrary | None`;
- `settings: MvpSettings`;
- `model_factory: Callable[[role], strands Model]`, where the roles are `"executor"`, `"planner"` and `"aux"`;
- `session_manager_factory: Callable[[session_id], SessionManager] | None`;
- `offload_storage: Storage | None`;
- `render_markdown: Callable | None`;
- `author_tool: Callable[..., dict] | None`, the toolsmith entry point that Lane T provides;
- `shell_guard: Callable[[str], str | None] | None`;
- `clock`.

Also `default_model_factory(settings)`, which builds OpenRouter `OpenAIModel`s with `context_window_limit`: 200k for the executor and 1M for the aux model. Check which limits are sensible and document them.

### 2. `agent/survey.py`

`survey(deps, run)` runs a self-contained Python survey script inside the sandbox through `deps.sandbox.exec`, using only the standard library. It collects:
- languages by extension and file counts;
- package manifests, Dockerfiles, CI configs and test commands;
- a top-level module list, and a light Python and JS import graph.

It stores the result as an artifact of kind `survey` and emits `survey_done`. On resume it is skipped if the artifact exists.

### 3. `agent/planner.py`

**Long-term plan (LTP):** planner model with typed output. Inputs:
- the goal and the survey;
- the top 5 lessons and gotchas from `knowledge.search(goal)`.

It saves `LongTermPlan` version 1 and emits `plan_created`.

**`next_steps(...)`:** from the LTP, the run digest, completed and failed steps, and open gotchas, it produces at most 3 `ShortTermPlan`s.
- Each has runnable acceptance `Check` commands, capability hints and a budget.
- It returns `[]` when the goal is complete.

**`revise_plan`:** called after repeated failure. It saves a new version and emits `plan_revised`.

Prompts live in `agent/prompts/*.md`.

### 4. `agent/selector.py`

1. `deps.tool_library.candidates(query, filters)`, where `query` is the objective plus the acceptance checks plus the capability hints, and `filters` come from the survey languages. It returns an empty list when `tool_library` is `None`.
2. The aux model, with typed output, picks at most `budgets.max_selected_tools`, with a reason each and the missing capabilities.
3. Store the picks on the step.
4. Emit `tools_selected` with the contract payload. `tool_schema_tokens` is estimated as `len(json(spec)) / 4` across the core and selected tools.

### 5. `agent/core_tools.py`

Strands `@tool` functions bound to a per-step context object:
- `complete_step(summary)`;
- `search_knowledge(query, kinds, mode)`;
- `search_tools(query)`;
- `load_tool(name, reason)`: at most `max_mid_step_loads`; uses `register_dynamic_tool`; emits `tool_loaded`;
- `create_tool(...)`: calls `deps.author_tool`, or returns "unavailable";
- `check_environment()`;
- `install_cli_tool(name)`: records the result in `run.cli_manifest` and emits `cli_installed` or `cli_refused`;
- `record_lesson(title, body, tags)` and `record_gotcha(title, symptom, cause, fix, tags)`: upsert into knowledge with sources and facets, and emit `lesson_recorded` or `gotcha_recorded`.

The sandbox shell and file editor tools are added alongside these.

### 6. `agent/guard.py`

`StepPolicy(InterventionHandler)`:
- denies any tool not in the step's allowed set, which is the core tools plus the selected tools plus mid-step loads;
- denies install-like shell commands when `deps.shell_guard` flags them, with guidance: "use install_cli_tool";
- stops the step on a turn, token or time budget, emitting `budget_exceeded`;
- checks `run.control` (pause or cancel) and the lease heartbeat every N tool calls. A lost lease raises a `LeaseLost` exception that aborts the run cleanly.

### 7. `agent/compaction.py`

`LoggedSummarizingConversationManager` subclasses the summarizing manager and emits a `compaction` event with `tokens_before`, `tokens_after`, `messages_before` and `messages_after`. It increments `run.usage.compactions`.

### 8. `agent/executor.py`

`execute_step(deps, run, step)` builds a fresh Agent:
- the executor model;
- the core tools, the selected tools (`tool_library.as_agent_tool`) and the sandbox tools;
- the compaction manager, with an aux-model summarization agent;
- a session manager from the factory, with `session_id = f"{run_id}.{step_id}"`;
- the `ContextOffloader` when `offload_storage` is set;
- `StepPolicy`;
- hooks that record `tool_call`, `tool_result` and `tool_error` and accumulate `Usage`.

**The brief** is pinned as the first message: the STP, the LTP excerpt, the digest, and the top 5 relevant lessons and gotchas, capped at about 3k tokens.

**The loop:** invoke the agent, then nudge with "continue; call complete_step when the acceptance checks should pass", until `complete_step` is called or the budget runs out.

**On resume:** a step in status `running` with an existing session continues it. See 11.

### 9. `agent/verify.py`

Run each `Check` through `deps.sandbox.exec(timeout)` and emit `step_verified`. The harness decides the result; the agent's claim is not trusted.

### 10. Reflection and digest

**`agent/reflect.py`:** the aux model, with typed output, produces lessons, gotchas and tool feedback.
- Lessons and gotchas are upserted into knowledge; for tool feedback, call `tool_library.record_use`.
- Then call `render_markdown` for each kind and write the results to `/workspace/repo/.portpilot/*.md`.

**`agent/digest.py`:** the aux model rewrites the run digest (1,500 tokens at most).
- It is stored as an artifact of kind `digest`.
- It is upserted into knowledge as `KnowledgeItem(id=f"digest_{run_id}", kind="run_digest")` with `dedupe=False`.

### 11. `agent/loop.py`

`run_migration(deps, run_id, worker_id)` is the state machine from MVP_PLAN §3.7.

1. `sandbox.ensure`, then the survey.
2. The LTP.
3. Loop over the steps. For each step, in order:
   - selecting tools;
   - running;
   - verifying: failure means retrying up to 2 times, recording the failure as a gotcha, then revising the plan; after that the step is marked failed and the loop moves on;
   - reflecting;
   - done.
4. When a step is done:
   - `commit_sha = sandbox.commit(...)`;
   - emit `checkpoint`;
   - update the digest.

**The run ends when:**
- `next_steps` returns `[]`, which means completed;
- a budget runs out, which means failed with a reason;
- a pause or cancel is requested.

**Resume:**
- Terminal steps are skipped.
- A step in `verifying` or `reflecting` redoes only that phase.
- A step in `running` continues its session. If that fails, `sandbox.restore(last_done_sha)` and restart the step.
- Every write is keyed by `step_id`, so repeating it is safe.
- Emit `resumed` when `run.current_step_id` was already set at start.

**Events:** every event matches the `CONTRACT.md` payload table.

## Tests

`tests/agent/` runs fully offline, using:
- a `ScriptedModel`: a minimal `strands.models.Model` subclass that replays canned responses, including tool calls;
- `InMemory*` stores and `LocalSandboxManager` from `core.fakes`, on a temp git repo under `runs/_pytest/`, because `$TMPDIR` isn't usable by git here;
- a `FakeToolLibrary` in `tests/agent/fakes.py`.

**Required cases:**
- **Offline end to end:** survey, LTP, 3 STPs, tools selected with reasons, a lesson recorded, a checkpoint commit per step, completed. Assert the event types and payload keys against the contract.
- **Guardrails:**
  - a disallowed tool is denied;
  - an install-like shell command is denied with guidance;
  - `load_tool` works up to the cap, and the call after that is refused.
- **Resume:** crash (raise inside a hook) at each step status, then resume with fresh deps on the same stores. No completed step re-runs, and the survey and LTP are not redone.
- **Retry:** a failing acceptance check retries, then revises the plan.
- **Controls:** pause and cancel via `run.control`.
- **Compaction:** a compaction event with a tiny `context_window_limit` and a scripted summarizer.
- **Budget:** exceeding a budget emits `budget_exceeded`.

**One `llm`-marked live test:**
- **Setup:** `LocalSandboxManager` and in-memory stores, on a tiny local Python repo you create under `runs/_pytest/`.
- **Goal:** "add a function `slugify` with tests".
- **Asserts:** the run completes, and the checks pass.
- **Cost:** keep it small. Run it once and report the tokens used.

## Done

- `uv run pytest tests/agent` is green offline.
- The live test has passed once.
- A plain `uv run pytest` is green.
- Ruff is clean.
- Everything is committed on `mvp/a`.

## Stop conditions

- **Interface change needed:** stop and report it; don't edit `core/` or `CONTRACT.md`.
- **Time box:** about 4 hours. If you run short, prioritize the offline end-to-end and resume tests.
