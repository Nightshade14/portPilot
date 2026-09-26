# Spike S2: the Strands agent runtime

- **Worktree:** `/Users/satyamchatrola/codes/personal/portPilot-spike-s2`, on branch `spike/s2`.
- **Read first:** `docs/plan/MVP_PLAN.md` sections 3.1, 3.5, 3.6, 3.7 and 3.11, and the S2 bullet in section 7.
- **Confirm APIs from source:** read the installed SDK under `.venv/lib/python3.12/site-packages/strands` (strands-agents 1.57.1) instead of guessing. The strandsagents.com docs are also available through `search_docs` / `fetch_doc`.
- **Where your work goes:**
  - code in `spikes/s2/`;
  - findings in `docs/spikes/S2_STRANDS.md`.
- **Don't touch:** `src/` or `tests/`.

## Environment

**Secrets from `.env`:** `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, and `MODEL_ID` (`anthropic/claude-sonnet-4.5`).

**A model construction that already works in this repo:**

```python
OpenAIModel(client_args={"api_key": key, "base_url": base_url}, model_id=model_id,
            params={"temperature": 0.1})   # from strands.models.openai
```

**Keep LLM spend small:** short prompts, fewer than about 60 model calls in total.

**Local Mongo:**
- Connect to `mongodb://127.0.0.1:27018/?directConnection=true`. It is the shared container `portpilot-mongo`; don't stop it.
- Use database `portpilot_spike_s2`, and drop it when you're done.

## Goals

Verify each goal by running code, and record the exact API names and signatures you used.

### 1. An agent per STP, with tools added at runtime

1. Build an Agent with 2 tools.
2. Mid-session, register a third through the registry: `register_dynamic_tool`, or whatever the correct public path turns out to be.
3. Confirm the model can call it on its next turn.

Then implement a minimal custom `AgentTool` subclass, `SandboxScriptTool`, with:
- `tool_name`;
- `tool_spec` built from a JSON schema;
- `tool_type`;
- an async `stream` that yields a result from a fake subprocess call.

Confirm the model calls it and the result comes back intact. Also confirm how to build a fresh Agent for each step with a different tool set.

### 2. Token cost of tool definitions

Send the same prompt twice, with 0 tools and with 11 realistic tool definitions:
- `shell`, `file_editor`, `complete_step`;
- `search_knowledge`, `search_tools`, `load_tool`, `create_tool`;
- `check_environment`, `install_cli_tool`;
- `record_lesson`, `record_gotcha`.

Using the usage metrics on `AgentResult`, report the difference in input tokens.

### 3. Compaction

Set up `SummarizingConversationManager(proactive_compression=..., summarization_agent=<agent on a cheap model>, pin_first=1, preserve_recent_messages=...)`.

1. Find in the source how the context-window size and utilization are computed for proactive compression with an OpenAI-compatible model. Is a context-window limit configured on the model, and through which parameter?
2. Force a compaction, for example with a small window or a low threshold plus long tool outputs.
3. Confirm the pinned first message survives it.
4. Write a subclass that records message counts and token estimates before and after, and fires a callback. That callback becomes our `compaction` event.

### 4. Offloading large tool outputs

Show a minimal custom `strands.storage.Storage` (dict-backed is fine) wired to the `ContextOffloader` plugin, so that an oversized tool result is stored and replaced by a preview. Record the exact configuration.

### 5. Durable sessions

1. Implement `AtlasSessionRepository(SessionRepository)`, with all abstract methods, on pymongo against the local Mongo.
2. Use it with `RepositorySessionManager`.

**Test in separate processes:**
1. Process A runs a few turns, including one tool call, and exits.
2. Process B, with the same session id, restores the conversation and continues it coherently.

**Test a kill mid-tool-call:**
1. Kill -9 process A while a tool (one that sleeps 30 s) is mid-call.
2. Restore in process B.
3. Document exactly what Strands does with the dangling tool call (an error? automatic repair?), and the minimal repair we must apply ourselves.

### 6. Guardrails

Write an `InterventionHandler.before_tool_call` that:
- denies a tool that isn't on an allow-list;
- denies a shell command matching an install pattern (for example `apt-get install`);
- returns guidance with each denial.

Confirm the model sees the denial and adapts.

### 7. A cheap secondary model

1. List candidate cheap models that support tools and structured output, from `GET https://openrouter.ai/api/v1/models` (public, no key needed).
2. Test 2 of them (for example a Claude Haiku model and one other) on:
   - `structured_output` into a small pydantic model;
   - summarizing a transcript of about 3k tokens.
3. Recommend one, giving its exact OpenRouter id and the evidence.

## Deliverable

`docs/spikes/S2_STRANDS.md`, containing:
- PASS or FAIL for each goal, with a working code snippet;
- gotchas: API quirks and anything experimental;
- the recommended secondary model id;
- the token numbers.

Commit on `spike/s2`.

## Stop conditions

- **Done:** all 7 goals have a verdict backed by evidence.
- **If an API doesn't exist as described:** record what does exist and the closest workable approach.
- **Stuck:** spend no more than about 15 minutes stuck on any one goal.
- **Time box:** about 75 minutes.
