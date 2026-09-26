"""Compaction: a compaction event with a tiny `context_window_limit` and a scripted
summarizer (docs/spikes/S2_STRANDS.md goal 3)."""

from __future__ import annotations

from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn
from strands import Agent, tool

from portpilot.agent.compaction import LoggedSummarizingConversationManager


@tool
def dump_large_output(n: int = 200) -> str:
    """Return a large synthetic text block to force big tool outputs."""
    return "\n".join(f"line {i}: padding padding padding padding padding padding" for i in range(n))


def test_compaction_event_logged_with_before_after_counts(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run()
    deps.run_store.create_run(run)

    executor_model = ScriptedModel(
        turns=[
            ScriptedTurn(tool_calls=[ScriptedToolCall("dump_large_output", {"n": 200})])
            for _ in range(6)
        ],
        context_window_limit=3000,
    )
    summarizer_model = ScriptedModel(
        turns=[ScriptedTurn(text="summary of the conversation so far")]
    )
    summarization_agent = Agent(model=summarizer_model, tools=[], system_prompt="summarizer")

    manager = LoggedSummarizingConversationManager(
        deps=deps,
        run_id=run.run_id,
        step_id="step_1",
        summarization_agent=summarization_agent,
        pin_first=1,
        preserve_recent_messages=4,
        proactive_compression={"compression_threshold": 0.7},
    )

    agent = Agent(
        model=executor_model,
        tools=[dump_large_output],
        system_prompt="STP BRIEF (pinned): verifying compaction.",
        conversation_manager=manager,
    )

    for i in range(6):
        agent(f"Call dump_large_output with n=200, then say OK-{i}.")

    events = deps.run_store.events(run.run_id)
    compaction_events = [e for e in events if e["type"] == "compaction"]
    assert compaction_events, "expected at least one compaction event to fire"
    for e in compaction_events:
        assert set(e["payload"].keys()) == {
            "tokens_before",
            "tokens_after",
            "messages_before",
            "messages_after",
        }
        assert e["payload"]["tokens_after"] <= e["payload"]["tokens_before"]
        assert e["payload"]["messages_after"] <= e["payload"]["messages_before"]

    run_after = deps.run_store.get_run(run.run_id)
    assert run_after.usage.compactions == len(compaction_events)

    # The pinned first message survives every compaction (pin_first=1 marks it via
    # metadata.custom.pinned, per docs/spikes/S2_STRANDS.md goal 3).
    first_message = agent.messages[0]
    assert first_message.get("metadata", {}).get("custom", {}).get("pinned") is True
    assert first_message["content"][0]["text"].startswith("Call dump_large_output with n=200")
