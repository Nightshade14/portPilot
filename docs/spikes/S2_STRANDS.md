# S2: the Strands agent runtime -- spike findings

Ran against the installed `strands-agents==1.57.1` (source read under
`.venv/lib/python3.12/site-packages/strands`), model `anthropic/claude-sonnet-4.5`
via OpenRouter for the executor agent, and `anthropic/claude-haiku-4.5` /
`google/gemini-2.5-flash-lite` as candidate cheap secondary models. All code
lives in `spikes/s2/`, run with `uv run python spikes/s2/<file>.py` from the
worktree root. Model spend for this spike: **~24 model calls** (well under the
~60 budget).

## Summary table

| Goal | Verdict |
|---|---|
| 1. Agent per STP, runtime tools, custom AgentTool | PASS |
| 2. Token cost of tool definitions | PASS -- 11 core tools cost 1,282 input tokens |
| 3. Compaction | PASS |
| 4. Offloading large tool outputs | PASS |
| 5. Durable sessions | PASS |
| 6. Guardrails | PASS |
| 7. Cheap secondary model | PASS -- recommend `google/gemini-2.5-flash-lite` |

---

## 1. Agent per STP, with tools added at runtime -- PASS

Code: `spikes/s2/goal1_agent_tools.py`

- `Agent(model=..., tools=[add, multiply])` builds a 2-tool agent from
  `@tool`-decorated functions.
- **Runtime registration is `agent.tool_registry.register_dynamic_tool(tool)`**
  -- there is no free-standing `register_dynamic_tool` function; it is a
  method on `ToolRegistry` (`strands/tools/registry.py:561`). It raises
  `ValueError` if the name already exists in either `registry` or
  `dynamic_tools`. Registered tools land in `agent.tool_registry.dynamic_tools`
  and are usable by the model on its very next turn -- confirmed: turn 1 used
  only `add`, turn 2 (after registering `subtract`) used `subtract`.
- **Custom `AgentTool` subclass** (`SandboxScriptTool`) needs exactly the 4
  members the plan expected: `tool_name` (str property), `tool_spec` (a
  `ToolSpec` dict -- `{"name", "description", "inputSchema": {"json": <JSON
  Schema>}}`), `tool_type` (any string, purely descriptive/for logging), and
  an **async** `stream(self, tool_use: ToolUse, invocation_state: dict,
  **kwargs) -> ToolGenerator` that yields dict(s) ending in one with
  `toolUseId`, `status`, `content`. `ToolGenerator = AsyncGenerator[Any,
  None]`. Confirmed the model calls it via natural-language instruction and
  the fake-subprocess stdout comes back intact and unmodified in the final
  answer.
- **Fresh Agent per step**: trivially just construct a new `Agent(...)` with a
  different `tools=` list. Each gets its own `ToolRegistry` instance
  (`id(step1.tool_registry) != id(step2.tool_registry)` was `True`). No shared
  mutable state to worry about between STPs as long as you don't reuse the
  same `Agent` object.

Gotcha: `EventLoopMetrics.tool_metrics` accumulates across the whole agent's
lifetime (all turns), not per-call -- if you need per-turn tool usage for
telemetry, diff the keys before/after the call rather than reading
`tool_metrics` fresh each time.

## 2. Token cost of tool definitions -- PASS

Code: `spikes/s2/goal2_tool_token_cost.py`

Same one-word prompt ("Say the word 'ready' and nothing else."), same model,
first with 0 tools, then with the 11 core tools from section 3.5 of the plan
(`shell`, `file_editor`, `complete_step`, `search_knowledge`, `search_tools`,
`load_tool`, `create_tool`, `check_environment`, `install_cli_tool`,
`record_lesson`, `record_gotcha`), each stubbed with a one-line docstring
description and a single `query: str` argument (a realistic lower bound --
real schemas with more fields would cost a bit more).

| | input tokens |
|---|---|
| 0 tools | 25 |
| 11 tools | 1,307 |
| **delta** | **1,282** |

That's the per-STP fixed overhead just for having the core tool set defined,
before any STP-specific tools are added. It's read from
`AgentResult.metrics.accumulated_usage["inputTokens"]` (an `EventLoopMetrics.Usage`
dict-like with `inputTokens`/`outputTokens`/`totalTokens`). The plan's "~6k
tokens per STP" budget (core + up to 8 selected tools) is consistent with this
number: 1.3k core + ~8 richer, real-schema tools plausibly fills the rest.

## 3. Compaction -- PASS

Code: `spikes/s2/goal3_compaction.py`

**3a. Where the context-window size and utilization are computed (OpenAI-compatible model):**

- `Model.context_window_limit` (property, `strands/models/model.py:203`) reads
  `self.get_config().get("context_window_limit")`.
- `context_window_limit` is a **top-level model-config kwarg** on
  `OpenAIModel.OpenAIConfig` (a `BaseModelConfig`, not nested inside `params`):
  ```python
  model = OpenAIModel(client_args={...}, model_id=model_id, params={"temperature": 0.1})
  model.update_config(context_window_limit=3000)   # or pass it at construction time
  ```
- If it is **not** configured, `Model.estimate_utilization()` falls back to
  `DEFAULT_CONTEXT_WINDOW_LIMIT = 200_000` (`strands/models/_defaults.py`) and
  logs a one-time warning. There's also a static per-model-id lookup table
  (`_CONTEXT_WINDOW_LIMITS` in the same file) the model can consult by base
  model ID, but an explicit `context_window_limit` always wins.
- `ConversationManager.__init__(proactive_compression=...)` resolves a
  `compression_threshold` (default 0.7) and registers a `BeforeModelCallEvent`
  hook. On every model call it computes
  `ratio = agent.model.estimate_utilization(event.projected_input_tokens)`
  and calls `reduce_context(agent=event.agent)` (no exception) once
  `ratio >= compression_threshold`.

**3b/c. Forced compaction + pinned-first-message survival:**

Set `context_window_limit=3000` on the executor model, added a
`dump_large_output` tool that returns ~200 padded lines per call, and drove 6
turns each calling that tool. **11 proactive compaction events fired** across
those 6 turns (multiple compressions per turn is possible -- the hook fires
before every model call, including the tool-result follow-up call). The
pinned first message survived every compaction: after the run it still reads
```json
{"role": "user", "content": [{"text": "Call dump_large_output with n=200, then say OK-0."}],
 "metadata": {"custom": {"pinned": true}}}
```
i.e. `pin_first=1` marks it via `metadata.custom.pinned`, and
`SummarizingConversationManager._summarize_oldest` always partitions pinned
messages out of the summarization range and re-prepends them
(`apply_pin_first` / `partition_pinned` in
`compression/pin_message.py`).

**3d. Subclass with before/after counts + callback:** `CompactionRecorder`
overrides `reduce_context`, snapshots `len(agent.messages)` and a cheap
chars/4 token estimate before calling `super().reduce_context(...)`, then again
after, and fires a user-supplied `on_compaction(event)` callback -- this is
our `compaction` event. Sample event:
```json
{"trigger": "proactive", "messages_before": 7, "messages_after": 6,
 "est_tokens_before": 5769, "est_tokens_after": 3078}
```

Gotcha: `agent.messages` is **empty before the first `agent(...)` call** --
the pinned first message can't be inspected until after the first turn runs
(the Agent builds it lazily from the prompt). Don't try to snapshot "before
any calls" state from `agent.messages`; read it after turn 1 instead.

## 4. Offloading large tool outputs -- PASS

Code: `spikes/s2/goal4_context_offloader.py`

- The plugin is `strands.vended_plugins.context_offloader.ContextOffloader`,
  not a top-level `strands.plugins.ContextOffloader` -- it's a *vended*
  plugin, imported from its own subpackage.
- It composes with a `Storage` **protocol**, not an ABC:
  `strands.storage.storage.Storage` (`runtime_checkable` `Protocol`) needs 4
  async methods: `write(key, data) -> None`, `read(key) -> bytes | None`,
  `delete(key) -> None`, `list(query: str) -> list[str]`. `search` has a
  default keyword-overlap implementation and is optional to override.
- A minimal dict-backed implementation (`DictStorage`, 5 methods incl.
  `search`) plugged straight into
  `ContextOffloader(storage=storage, max_result_tokens=200, preview_tokens=50)`,
  wired via `Agent(plugins=[...])`.
- Exact configuration that worked:
  ```python
  from strands.vended_plugins.context_offloader import ContextOffloader
  agent = Agent(model=model, tools=[huge_file_read],
                plugins=[ContextOffloader(storage=DictStorage(), max_result_tokens=200, preview_tokens=50)])
  ```
- Confirmed: a tool call whose result exceeded 200 estimated tokens was
  intercepted, stored under a namespaced key (`ContextOffloader` auto-prefixes
  raw `Storage` with `offloader/` unless already namespaced), and replaced in
  context with a text preview + reference; the model then called the
  auto-registered `retrieve_offloaded_content` tool and answered correctly
  from the retrieved data. One key stored: `offloader/<toolUseId>_0`.

Gotcha: `ContextOffloader` auto-registers a `retrieve_offloaded_content` tool
on the agent -- if you don't want that (e.g. a step whose tool set is tightly
curated), pass `include_retrieval_tool=False`, but then the model has no way
to get the full content back; only the preview.

## 5. Durable sessions -- PASS

Code: `spikes/s2/atlas_session_repository.py` (the repository),
`spikes/s2/goal5_process_a.py` / `goal5_process_b.py` (separate-process
continuity test), `spikes/s2/goal5_kill_test_a.py` /
`goal5_kill_test_b.py` (kill -9 mid-tool-call test).

**5a. `AtlasSessionRepository(SessionRepository)`:** implemented all 9 methods
(`create_session`, `read_session`, `create_agent`, `read_agent`,
`update_agent`, `create_message`, `read_message`, `update_message`,
`list_messages`; the 3 multi-agent methods are optional and left at their
`NotImplementedError` defaults) on top of `pymongo.MongoClient` against
`mongodb://127.0.0.1:27018/?directConnection=true`, db
`portpilot_spike_s2`, three collections (`sessions`, `agents`, `messages`).
Each dataclass (`Session`, `SessionAgent`, `SessionMessage`) has
`.to_dict()`/`.from_dict()` built in, so the repository is basically "call
`to_dict()`, stamp an `_id`, `replace_one(upsert=True)`" and the inverse on
read -- no manual (de)serialization of the message/tool-call payloads needed.

**5b. `RepositorySessionManager(session_id=..., session_repository=repo)`**,
handed to `Agent(session_manager=session_manager, agent_id="spike-agent")`.

**Cross-process continuity test:**
- Process A: fresh session, 2 turns (one calling a `remember_fact` tool to
  store "42", one asking what was stored), exits. `message_count_after_A: 6`.
- Process B: same `session_id`/`agent_id`, freshly constructed `Agent` with
  the **same** `RepositorySessionManager` wiring. On construction it restored
  6 messages from Mongo (`message_count_on_restore: 6`), and a third turn
  asking "what number did I ask you to remember earlier" answered `"42"`
  correctly with **no tool call** -- pure conversation continuity across the
  process boundary. `SessionManager.initialize()` is what does the restore;
  it also runs `_fix_broken_tool_use` on the restored history defensively.

**Kill -9 mid-tool-call test:** Started a process with a `slow_tool(seconds=30)`
tool call in flight, waited for the tool to actually start (confirmed via a
print inside the tool), then `kill -9`'d the real python pid (note: with `uv
run`, the pid you get from backgrounding the wrapper is **not** the pid
running your script -- grab the real one, e.g. by having the script print its
own `os.getpid()`).

Mongo after the kill held exactly 2 messages: the user prompt, and an
assistant message ending in a **dangling `toolUse`** block with no matching
`toolResult` -- the crash happened before the tool's result was ever
persisted.

**What Strands does with it, exactly:** nothing automatic happens at restore
time for a *trailing* dangling toolUse --
`RepositorySessionManager._fix_broken_tool_use` explicitly **excludes the last
message** from its toolUse/toolResult repair pass (see the comment "Trailing
message excluded (handled by agent class at prompt-arrival time)" at
`repository_session_manager.py:342`). The repair instead happens lazily, in
`Agent._convert_prompt_to_messages`, the moment you call `agent(...)` again:
if `self.messages[-1]` contains a `toolUse`, it auto-appends a synthetic user
message with one `toolResult` per dangling `toolUseId`:
```python
{"toolResult": {"toolUseId": tool_use_id, "status": "error",
                "content": [{"text": "Tool was interrupted."}]}}
```
(`generate_missing_tool_result_content` in `tools/_tool_helpers.py`). Confirmed
end to end: Process B restored the 2-message history, and on the next call the
model said "Not finished" -- exactly what you'd expect having just seen an
`status: error, "Tool was interrupted."` result.

**The minimal repair we must apply ourselves: none**, for the common case of a
crash strictly mid-tool-call (nothing yet appended after the toolUse). It's
automatic and needs no intervention from us. The repair Strands does NOT do
for you: it doesn't know or care that `slow_tool` might actually still be
running somewhere (e.g. in a container that outlived the worker process) --
"interrupted" is asserted, not verified. If a real sandboxed tool could still
be mid-flight in a container after a worker restart, our own
`SandboxManager.ensure(run_id)` reattach logic (plan section 3.7) needs to
actually check/kill that straggler; Strands's repair only fixes the
*conversation*, not the *side effect*. `_fix_broken_tool_use` (the
non-trailing-message repair path) is a good safety net for the rarer case of
a corrupted/paginated history with an orphaned toolResult or a stale
toolUse/toolResult ID mismatch further back in history, but did not trigger
in this test since the dangling call was the trailing message.

Both test databases (`s2-goal5-durable`, `s2-goal5-kill` documents) were
cleared during the run; `portpilot_spike_s2` is dropped entirely at the end of
this spike (see Cleanup).

## 6. Guardrails -- PASS

Code: `spikes/s2/goal6_guardrails.py`

- Subclassed `strands.interventions.InterventionHandler`, set a class-level
  `name`, and overrode `before_tool_call(self, event) -> Deny | Proceed`.
  `event.tool_use` is a `ToolUse` dict (`{"name", "input", "toolUseId"}`).
- Wired via **`Agent(interventions=[handler])`** -- not
  `intervention_handlers=`, which doesn't exist; the actual kwarg is
  `interventions`, and the internal registry class is
  `InterventionRegistry`.
- Denied one tool outright for not being on an allow-list
  (`{"shell", "check_environment"}`) and denied a `shell` call whose
  `input["command"]` matched an install-pattern regex (`apt-get install` /
  `apt install` / `pip install`), returning
  `Deny(reason="...")` with a human-readable pointer to `install_cli_tool` in
  both cases.
- Confirmed the model sees the denial reason (it's surfaced to the model as
  the tool's cancellation message) and adapts on its very next tool choice:
  asked to call `dangerous_tool`, then explained the allow-list denial in
  prose; asked to run `apt-get install curl` via `shell`, it explained the
  denial and named `install_cli_tool` as the correct path -- it did not retry
  the same denied call.

## 7. A cheap secondary model -- PASS

Code: `spikes/s2/goal7_cheap_model.py`

Pulled `GET https://openrouter.ai/api/v1/models` (458 models, no key needed)
and filtered to models supporting `tools` + `structured_outputs` with low
per-token pricing. Candidates considered: `anthropic/claude-haiku-4.5`,
`google/gemini-2.5-flash-lite`, `openai/gpt-4o-mini`, `mistralai/mistral-small-3.2-24b-instruct`,
several `qwen/*-flash` variants. Tested the two most relevant to our stack
(Anthropic family consistency vs. cheapest capable alternative):

| Model | Structured output | Summarize ~3k-token transcript | Notes |
|---|---|---|---|
| `anthropic/claude-haiku-4.5` | OK, 2.68 s | OK, 1.97 s, 90 output tokens | pricing: $1/$5 per M tokens |
| `google/gemini-2.5-flash-lite` | OK, 0.58 s | OK, 0.75 s, 58 output tokens | pricing: $0.10/$0.40 per M tokens |

Both produced correct, on-schema `StepVerdict` objects
(`passed: bool, summary: str, risk_level: str`) and coherent <80-word
summaries of the synthetic 54-step migration transcript.

**Recommendation: `google/gemini-2.5-flash-lite`.** It was ~3.5x faster on
both tests and is roughly 10x cheaper per token than Haiku 4.5, while passing
both checks with no quality problems observed on this small sample. Use
`anthropic/claude-haiku-4.5` as the fallback if Gemini's tool-calling or
structured-output reliability turns out worse at larger scale (this spike's
sample size is n=1 per test, not a statistically powered comparison).

Gotcha: `Agent.structured_output(...)` is **deprecated** as of this SDK
version -- it still works (used here to keep the goal-7 code simple and
model-swappable) but emits `DeprecationWarning: ... You should pass in
structured_output_model directly into the agent invocation.` The plan's
"planner/tool-selector/reflection/digest calls return validated models" work
(section 3.1, 3.5) should use `structured_output_model=` on `Agent(...)` or on
the call, not the deprecated method, in real harness code.

---

## Gotchas (cross-cutting)

- `register_dynamic_tool` is `agent.tool_registry.register_dynamic_tool(tool)`, a method, not
  a free function importable from `strands.tools`.
- `ContextOffloader` lives under `strands.vended_plugins.context_offloader`, not `strands.plugins`.
- `context_window_limit` is a **top-level** `OpenAIModel`/`BaseModelConfig` kwarg, sibling to
  `params=`, not nested inside it.
- The Agent constructor kwarg for guardrails is `interventions=`, not `intervention_handlers=`.
- `EventLoopMetrics.tool_metrics` and `.accumulated_usage` accumulate over the agent's whole
  lifetime, not per-call -- diff before/after if you need per-turn numbers.
- `agent.messages` is empty until after the first `agent(...)` call.
- A `kill -9`'d Strands process leaves a **trailing dangling `toolUse`** in the persisted
  session; Strands repairs this itself, lazily, on the next `agent(...)` call (synthetic
  `status: "error"` toolResult), not at session-restore time. Only non-trailing corruption is
  repaired by `RepositorySessionManager._fix_broken_tool_use` at restore time.
- `Agent.structured_output(...)` is deprecated in favor of `structured_output_model=`.
- With `uv run script.py &`, the backgrounded shell pid is the `uv` wrapper, not the actual
  Python process -- get the real pid from inside the script if you need to `kill -9` it precisely.

## Recommended secondary model

`google/gemini-2.5-flash-lite` (OpenRouter id, exact) for the cheap-model roles in section 3.1 /
3.6 (`SummarizingConversationManager.summarization_agent`, tool selector, reflection/digest calls),
with `anthropic/claude-haiku-4.5` as the fallback for closer Anthropic-family behavior parity if
Gemini proves less reliable at scale.

## Token numbers

- 11 core tool definitions: **+1,282 input tokens** vs. 0 tools (25 -> 1,307).
- Compaction test: 11 proactive-compression events across 6 turns with `context_window_limit=3000`;
  sample before/after estimated-token deltas from ~5,769 -> ~3,078 and ~8,921 -> ~6,008.
- Structured-output/summarization test on a ~3,100-input-token transcript: Haiku 4.5 used 90 output
  tokens in 1.97s; Gemini 2.5 Flash Lite used 58 output tokens in 0.75s.

## Cleanup

`portpilot_spike_s2` Mongo database dropped at the end of this spike via
`AtlasSessionRepository.drop_database()`. The shared `portpilot-mongo`
container itself was left running, untouched.
