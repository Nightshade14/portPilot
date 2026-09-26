"""Goal 3: SummarizingConversationManager with proactive compression."""

from __future__ import annotations

import json

from common import load_env, make_model
from strands import Agent, tool
from strands.agent.conversation_manager.summarizing_conversation_manager import (
    SummarizingConversationManager,
)


class CompactionRecorder(SummarizingConversationManager):
    """Subclass that records message-count/token-estimate before+after and fires a callback."""

    def __init__(self, *args, on_compaction=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._on_compaction = on_compaction
        self.events: list[dict] = []

    def reduce_context(self, agent, e=None, **kwargs) -> None:
        before_count = len(agent.messages)
        before_tokens = self._estimate_tokens(agent)
        super().reduce_context(agent, e=e, **kwargs)
        after_count = len(agent.messages)
        after_tokens = self._estimate_tokens(agent)
        event = {
            "trigger": "reactive_overflow" if e is not None else "proactive",
            "messages_before": before_count,
            "messages_after": after_count,
            "est_tokens_before": before_tokens,
            "est_tokens_after": after_tokens,
        }
        self.events.append(event)
        if self._on_compaction:
            self._on_compaction(event)

    @staticmethod
    def _estimate_tokens(agent) -> int:
        # Cheap, dependency-free estimate: chars/4 across all text blocks.
        total_chars = 0
        for msg in agent.messages:
            for block in msg.get("content", []):
                if "text" in block:
                    total_chars += len(block["text"])
                elif "toolResult" in block:
                    for c in block["toolResult"].get("content", []):
                        if "text" in c:
                            total_chars += len(c["text"])
        return total_chars // 4


@tool
def dump_large_output(n: int = 200) -> str:
    """Return a large synthetic text block (n repeated lines) to force big tool outputs."""
    return "\n".join(f"line {i}: padding padding padding padding padding padding" for i in range(n))


def main() -> None:
    env = load_env()
    summarizer_model = make_model(env, model_id="anthropic/claude-haiku-4.5")
    summarization_agent = Agent(
        model=summarizer_model, tools=[], system_prompt="You summarize conversations concisely."
    )

    fired = []
    manager = CompactionRecorder(
        proactive_compression={"compression_threshold": 0.7},
        summarization_agent=summarization_agent,
        pin_first=1,
        preserve_recent_messages=4,
        on_compaction=lambda ev: fired.append(ev),
    )

    main_model = make_model(env)
    # Force a small context window so a handful of exchanges cross the 70% threshold quickly.
    main_model.update_config(context_window_limit=3000)

    agent = Agent(
        model=main_model,
        tools=[dump_large_output],
        system_prompt="STP BRIEF (pinned): You are the S2 spike agent verifying compaction.",
        conversation_manager=manager,
    )

    pinned_first_message = dict(agent.messages[0]) if agent.messages else None

    responses = []
    for i in range(6):
        r = agent(f"Call dump_large_output with n=200, then say OK-{i}.")
        responses.append(str(r).strip())

    result = {
        "compaction_events_fired": fired,
        "num_compactions": len(manager.events),
        "pin_first_message_before": pinned_first_message,
        "first_message_after_runs": agent.messages[0] if agent.messages else None,
        "context_window_limit_configured": main_model.context_window_limit,
        "final_message_count": len(agent.messages),
        "removed_message_count": manager.removed_message_count,
        "responses": responses,
    }
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
