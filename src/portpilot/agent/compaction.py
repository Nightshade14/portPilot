"""Compaction logging (lane-a.md build step 7).

`LoggedSummarizingConversationManager` subclasses `SummarizingConversationManager`
(verified constructor per docs/spikes/S2_STRANDS.md goal 3 / spikes/s2/goal3_compaction.py)
and emits a `compaction` event with token/message counts before and after, incrementing
`run.usage.compactions`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from strands.agent.conversation_manager.summarizing_conversation_manager import (
    SummarizingConversationManager,
)

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps


def _estimate_tokens(agent: Any) -> int:
    """Cheap chars/4 estimate across all text blocks, matching the S2 spike's recorder."""
    total_chars = 0
    for msg in agent.messages:
        for block in msg.get("content", []):
            if "text" in block:
                total_chars += len(block["text"])
            elif "toolResult" in block:
                for c in block["toolResult"].get("content", []):
                    if "text" in c:
                        total_chars += len(c["text"])
            elif "toolUse" in block:
                total_chars += len(str(block["toolUse"].get("input", "")))
    return total_chars // 4


class LoggedSummarizingConversationManager(SummarizingConversationManager):
    """Emits `compaction` (deps.run_store.log_event) on every `reduce_context` call and
    increments `run.usage.compactions`. `deps`/`run_id`/`step_id` are bound at
    construction so `agent/executor.py` can hand one instance to each fresh `Agent`."""

    def __init__(
        self,
        *args: Any,
        deps: AgentDeps,
        run_id: str,
        step_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._deps = deps
        self._run_id = run_id
        self._step_id = step_id

    def reduce_context(self, agent: Any, e: Any = None, **kwargs: Any) -> None:
        messages_before = len(agent.messages)
        tokens_before = _estimate_tokens(agent)

        super().reduce_context(agent, e=e, **kwargs)

        messages_after = len(agent.messages)
        tokens_after = _estimate_tokens(agent)

        self._deps.run_store.log_event(
            self._run_id,
            "compaction",
            self._step_id,
            {
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "messages_before": messages_before,
                "messages_after": messages_after,
            },
        )
        run = self._deps.run_store.get_run(self._run_id)
        run.usage.compactions += 1
        self._deps.run_store.update_run(self._run_id, usage=run.usage)


__all__ = ["LoggedSummarizingConversationManager"]
