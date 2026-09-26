"""Store backend selection (MVP_PLAN 3.7/4). Owner: Lane M."""

from __future__ import annotations

from portpilot.core.config import MvpSettings
from portpilot.core.interfaces import RunStore, ToolStore


def open_stores(settings: MvpSettings) -> tuple[RunStore, ToolStore]:
    """`settings.store_backend == "memory"` returns the fakes from `core.fakes`;
    `"atlas"` returns the Atlas stores (requires `settings.mongodb_uri`)."""
    if settings.store_backend == "memory":
        from portpilot.core.fakes import InMemoryRunStore, InMemoryToolStore

        return InMemoryRunStore(), InMemoryToolStore()
    if settings.store_backend == "atlas":
        from portpilot.store.v2.atlas import AtlasRunStore, AtlasToolStore

        if not settings.mongodb_uri:
            raise ValueError("store_backend='atlas' requires settings.mongodb_uri")
        run_store = AtlasRunStore(settings.mongodb_uri, settings.mongodb_db)
        tool_store = AtlasToolStore(settings.mongodb_uri, settings.mongodb_db)
        return run_store, tool_store
    raise ValueError(f"unknown store_backend={settings.store_backend!r}")


def close_stores(run_store: RunStore, tool_store: ToolStore) -> None:
    """Close both stores if they support it (the in-memory fakes do not)."""
    for store in (run_store, tool_store):
        close = getattr(store, "close", None)
        if callable(close):
            close()


__all__ = ["close_stores", "open_stores"]
