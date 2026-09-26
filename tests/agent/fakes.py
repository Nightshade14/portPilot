"""Test-only fakes for `tests/agent/` (lane-a.md: "runs fully offline").

`ScriptedModel` is a minimal `strands.models.Model` subclass that replays canned
responses, including tool calls, so the offline suite never calls a real LLM.
`FakeToolLibrary` is a minimal `ToolLibrary` stand-in.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any, TypeVar

from pydantic import BaseModel
from strands.models.model import Model
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

T = TypeVar("T", bound=BaseModel)


class ScriptedToolCall:
    """One tool call a `ScriptedModel` turn should make."""

    def __init__(self, name: str, input: dict[str, Any]) -> None:
        self.name = name
        self.input = input


class ScriptedTurn:
    """One `agent(...)` turn's canned behavior: some tool calls, then optional text."""

    def __init__(self, tool_calls: list[ScriptedToolCall] | None = None, text: str = "") -> None:
        self.tool_calls = tool_calls or []
        self.text = text


class ScriptedModel(Model):
    """Replays a fixed sequence of `ScriptedTurn`s, one per `agent(...)` call.

    Turns are consumed in order; calling past the end of the script repeats the last
    turn (so a test's "continue; call complete_step" nudge loop does not crash if the
    script under-specifies trailing turns -- write enough turns to reach the exit
    condition instead of relying on this).

    Also answers `structured_output` calls from a separate, keyed queue
    (`structured_output_queue`), since planner/selector/reflect/digest calls use typed
    output rather than the tool-call turn script.
    """

    def __init__(
        self,
        turns: list[ScriptedTurn] | None = None,
        structured_output_queue: list[BaseModel] | None = None,
        context_window_limit: int | None = None,
    ) -> None:
        self._turns = list(turns or [])
        self._turn_index = 0
        self._awaiting_tool_followup = False
        self._last_turn_text = ""
        self._structured_queue = list(structured_output_queue or [])
        self._config: dict[str, Any] = {}
        if context_window_limit is not None:
            self._config["context_window_limit"] = context_window_limit
        self.calls: list[Messages] = []

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> Any:
        return self._config

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any], None]:
        """Direct `Model.structured_output(...)` callers (not the `structured_output_model=`
        path on `Agent`, which forces a tool call through `stream()` instead -- see
        `_stream_structured` below)."""
        index = next(
            (i for i, v in enumerate(self._structured_queue) if isinstance(v, output_model)), None
        )
        if index is None:
            raise RuntimeError("ScriptedModel.structured_output_queue exhausted")
        yield {"output": self._structured_queue.pop(index)}

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: Any = None,
        system_prompt_content: Any = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: Any = None,
        agent_metadata: Any = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        self.calls.append(messages)

        # `agent(prompt, structured_output_model=X)` adds a synthetic tool spec named
        # `X.__name__` (see strands.tools.structured_output.structured_output_utils) and
        # expects the model to call it. When that tool is on offer, answer it from
        # `structured_output_queue` as an ordinary tool call instead of consulting the
        # turn script.
        structured_names = {
            spec["name"] for spec in (tool_specs or [])
        } & self._structured_pending_names()
        if structured_names:
            tool_name = next(iter(structured_names))
            async for event in self._stream_structured(tool_name):
                yield event
            return

        # Strands re-invokes `stream()` immediately after a tool call's result is
        # appended, in the SAME `agent(...)` call, without returning control to test
        # code in between. So a scripted turn with tool_calls consumes the NEXT
        # `stream()` call too, as a plain `end_turn` (optionally with `turn.text`) --
        # otherwise the turn's tool call would repeat forever (each `ScriptedTurn` is
        # meant to model one whole `agent(...)` invocation, not one model hop).
        if self._awaiting_tool_followup:
            self._awaiting_tool_followup = False
            async for event in self._stream_followup_text(self._last_turn_text):
                yield event
            return

        turn = (
            self._turns[min(self._turn_index, len(self._turns) - 1)]
            if self._turns
            else ScriptedTurn()
        )
        self._turn_index += 1

        yield {"messageStart": {"role": "assistant"}}

        if turn.text and not turn.tool_calls:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": turn.text}}}
            yield {"contentBlockStop": {"contentBlockIndex": 0}}

        for i, call in enumerate(turn.tool_calls):
            tool_use_id = f"tooluse_{uuid.uuid4().hex[:16]}"
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": i,
                    "start": {"toolUse": {"name": call.name, "toolUseId": tool_use_id}},
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": i,
                    "delta": {"toolUse": {"input": json.dumps(call.input)}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": i}}

        stop_reason = "tool_use" if turn.tool_calls else "end_turn"
        if turn.tool_calls:
            self._awaiting_tool_followup = True
            self._last_turn_text = turn.text
        yield {"messageStop": {"stopReason": stop_reason}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "metrics": {"latencyMs": 1},
            }
        }

    async def _stream_followup_text(self, text: str) -> AsyncGenerator[StreamEvent, None]:
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text or "OK."}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25},
                "metrics": {"latencyMs": 1},
            }
        }

    def _structured_pending_names(self) -> set[str]:
        return {type(v).__name__ for v in self._structured_queue}

    async def _stream_structured(self, tool_name: str) -> AsyncGenerator[StreamEvent, None]:
        index = next(
            i for i, v in enumerate(self._structured_queue) if type(v).__name__ == tool_name
        )
        value = self._structured_queue.pop(index)
        tool_use_id = f"tooluse_{uuid.uuid4().hex[:16]}"
        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"name": tool_name, "toolUseId": tool_use_id}},
            }
        }
        yield {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": value.model_dump_json()}},
            }
        }
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "metrics": {"latencyMs": 1},
            }
        }


class FakeToolLibrary:
    """Minimal `ToolLibrary` stand-in: `candidates` returns a fixed list; the rest are
    no-op recorders good enough for offline tests of `agent/selector.py` and
    `agent/executor.py`."""

    def __init__(self, cards: list[Any] | None = None) -> None:
        from portpilot.core.models import ToolCard

        self._cards: list[ToolCard] = cards or []
        self.record_use_calls: list[tuple[str, int, str, bool, str]] = []
        self.as_agent_tool_calls: list[tuple[str, int, str]] = []

    def propose(self, draft, run_id, step_id):  # pragma: no cover - unused by lane A tests
        raise NotImplementedError("FakeToolLibrary.propose is not exercised by tests/agent")

    def validate(self, name, version, run_id):  # pragma: no cover
        raise NotImplementedError("FakeToolLibrary.validate is not exercised by tests/agent")

    def promote(self, name, version, run_id):  # pragma: no cover
        raise NotImplementedError("FakeToolLibrary.promote is not exercised by tests/agent")

    def candidates(self, query: str, filters: dict[str, Any] | None = None, limit: int = 20):
        return list(self._cards[:limit])

    def as_agent_tool(self, record, run_id: str):
        self.as_agent_tool_calls.append((record.name, record.version, run_id))
        from strands.types.tools import AgentTool

        class _StubAgentTool(AgentTool):
            def __init__(self, name: str) -> None:
                super().__init__()
                self._name = name

            @property
            def tool_name(self) -> str:
                return self._name

            @property
            def tool_spec(self):
                return {
                    "name": self._name,
                    "description": f"library tool {self._name}",
                    "inputSchema": {"json": {"type": "object", "properties": {}}},
                }

            @property
            def tool_type(self) -> str:
                return "library_stub"

            async def stream(self, tool_use, invocation_state, **kwargs):
                yield {
                    "toolUseId": tool_use["toolUseId"],
                    "status": "success",
                    "content": [{"text": "stub library tool result"}],
                }

        return _StubAgentTool(record.name)

    def record_use(self, name: str, version: int, run_id: str, ok: bool, note: str = "") -> None:
        self.record_use_calls.append((name, version, run_id, ok, note))


__all__ = ["FakeToolLibrary", "ScriptedModel", "ScriptedToolCall", "ScriptedTurn"]
