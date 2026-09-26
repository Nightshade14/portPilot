"""Minimal production composition for the bounded live-agent demo."""

from __future__ import annotations

from portpilot.agent.deps import AgentDeps, default_model_factory
from portpilot.core.config import MvpSettings
from portpilot.core.fakes import FakeEmbedder, InMemoryKnowledgeStore
from portpilot.sandbox import looks_like_install, open_sandbox
from portpilot.store.v2.factory import open_stores


def build_agent_deps(settings: MvpSettings) -> AgentDeps:
    """Compose the live worker without the deferred tool-library features.

    Runs and events use the configured store; knowledge is intentionally in-memory
    for the bounded demo so the agent does not require Atlas Search indexes or Voyage.
    """
    run_store, tool_store = open_stores(settings)
    sandbox, installer = open_sandbox(settings)
    return AgentDeps(
        run_store=run_store,
        tool_store=tool_store,
        knowledge=InMemoryKnowledgeStore(FakeEmbedder()),
        sandbox=sandbox,
        installer=installer,
        tool_library=None,
        settings=settings,
        model_factory=default_model_factory(settings),
        shell_guard=looks_like_install,
    )


__all__ = ["build_agent_deps"]
