"""Dependency container for the agent loop (lane-a.md build step 1).

`AgentDeps` bundles the frozen-core interfaces plus the callables the agent needs but
does not own the implementation of (model construction, session persistence, tool
authoring, shell-command guarding). Other lanes' real implementations get injected by
the Lead at integration time; tests inject fakes / stubs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from portpilot.core.config import MvpSettings
from portpilot.core.interfaces import CliInstaller, KnowledgeStore, SandboxManager, ToolLibrary
from portpilot.core.interfaces import RunStore as _RunStore
from portpilot.core.interfaces import ToolStore as _ToolStore

if TYPE_CHECKING:  # pragma: no cover
    from strands.models import Model
    from strands.session.session_manager import SessionManager
    from strands.storage.storage import Storage

ModelRole = Literal["executor", "planner", "aux"]

# Context-window budgets per model role (lane-a.md build step 1: "check which limits
# are sensible and document them"). The executor and planner share `settings.model_id`
# (verified as anthropic/claude-sonnet-4.5, a 200k-context model per OpenRouter's
# listing); 200k lets an STP run for a while before proactive compression (70% => fires
# around ~140k tokens used). The aux model (settings.model_id_aux, e.g.
# google/gemini-2.5-flash-lite) is used for short structured-output calls (selection,
# reflection, digest, summarization) that never approach a large window on their own,
# but S2 goal 3 drove a summarization agent with no special limit; giving it a large
# window here (1M, matching Gemini 2.5 Flash Lite's real limit) means the aux model is
# never the thing that triggers unwanted compaction of its own (single-shot) calls.
EXECUTOR_CONTEXT_WINDOW_LIMIT = 200_000
AUX_CONTEXT_WINDOW_LIMIT = 1_000_000


def default_model_factory(settings: MvpSettings) -> Callable[[ModelRole], Model]:
    """Build OpenRouter `OpenAIModel`s per role, verified per docs/spikes/S2_STRANDS.md.

    `context_window_limit` is a top-level `OpenAIModel` config kwarg (sibling to
    `params=`), required for `SummarizingConversationManager`'s proactive compression to
    have a real threshold instead of the 200k default fallback.
    """

    def factory(role: ModelRole) -> Model:
        from strands.models.openai import OpenAIModel

        model_id = settings.model_id if role in ("executor", "planner") else settings.model_id_aux
        limit = (
            EXECUTOR_CONTEXT_WINDOW_LIMIT
            if role in ("executor", "planner")
            else AUX_CONTEXT_WINDOW_LIMIT
        )
        return OpenAIModel(
            client_args={
                "api_key": settings.openrouter_api_key,
                "base_url": settings.openrouter_base_url,
                "timeout": 120.0,
                "max_retries": 2,
            },
            model_id=model_id,
            params={"temperature": settings.model_temperature},
            context_window_limit=limit,
        )

    return factory


@dataclass
class AgentDeps:
    """Everything `agent/*` needs, injected rather than imported directly.

    Depending only on `core/` protocols plus these callables keeps this package free of
    imports from `store.v2`, `knowledge`, `sandbox`, `toollib` (lane-a.md: "Do not
    import packages other lanes are building").
    """

    run_store: _RunStore
    tool_store: _ToolStore
    knowledge: KnowledgeStore
    sandbox: SandboxManager
    installer: CliInstaller
    tool_library: ToolLibrary | None
    settings: MvpSettings
    model_factory: Callable[[ModelRole], Model]
    session_manager_factory: Callable[[str], SessionManager] | None = None
    offload_storage: Storage | None = None
    render_markdown: Callable[..., str] | None = None
    author_tool: Callable[..., dict[str, Any]] | None = None
    """The toolsmith entry point Lane T provides. Called exactly as
    `author_tool(run_id=str, step_id=str, name=str, purpose=str, requirements=str) -> dict`,
    returning `{"ok": bool, "name": str, "version": int | None, "reason": str}`. The tool
    library -- not this package -- emits `tool_created` / `tool_validated` /
    `tool_promoted` / `tool_rejected`; `agent/core_tools.py` only calls it and, on
    success, makes the new tool usable in the same step (see `create_tool`)."""
    shell_guard: Callable[[str], str | None] | None = None
    clock: Callable[[], Any] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.clock is None:
            from portpilot.core.models import utcnow

            self.clock = utcnow


__all__ = [
    "AUX_CONTEXT_WINDOW_LIMIT",
    "EXECUTOR_CONTEXT_WINDOW_LIMIT",
    "AgentDeps",
    "ModelRole",
    "default_model_factory",
]
