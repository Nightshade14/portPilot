"""`build_api_deps(settings) -> ApiDeps` (lane-p.md step 2). Owner: Lane P."""

from __future__ import annotations

import logging

from portpilot.api.app import ApiDeps
from portpilot.core.config import MvpSettings
from portpilot.core.interfaces import KnowledgeStore, RunStore, SandboxManager, ToolStore
from portpilot.knowledge import AtlasKnowledgeStore, make_embedder
from portpilot.store.v2.factory import open_stores

logger = logging.getLogger(__name__)


def _open_knowledge_store(settings: MvpSettings) -> KnowledgeStore:
    if settings.store_backend == "memory":
        from portpilot.core.fakes import InMemoryKnowledgeStore

        return InMemoryKnowledgeStore(make_embedder(settings))
    if not settings.mongodb_uri:
        raise ValueError("store_backend='atlas' requires settings.mongodb_uri")
    return AtlasKnowledgeStore(settings.mongodb_uri, settings.mongodb_db, make_embedder(settings))


def _open_sandbox(settings: MvpSettings) -> SandboxManager | None:
    """None when `portpilot.sandbox` doesn't expose `open_sandbox` on this base (lane brief)."""
    try:
        from portpilot.sandbox import open_sandbox
    except ImportError:
        logger.warning("portpilot.sandbox.open_sandbox not available; running without a sandbox")
        return None
    try:
        manager, _installer = open_sandbox(settings)
    except Exception:  # pragma: no cover - defensive: a broken Docker env shouldn't crash boot
        logger.warning("open_sandbox(settings) failed; running without a sandbox", exc_info=True)
        return None
    return manager


def build_api_deps(settings: MvpSettings) -> ApiDeps:
    run_store: RunStore
    tool_store: ToolStore
    run_store, tool_store = open_stores(settings)
    knowledge = _open_knowledge_store(settings)
    sandbox = _open_sandbox(settings)
    return ApiDeps(
        run_store=run_store,
        tool_store=tool_store,
        knowledge=knowledge,
        sandbox=sandbox,
        settings=settings,
    )


__all__ = ["build_api_deps"]
