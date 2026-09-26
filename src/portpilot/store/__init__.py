"""Persistence layer. `get_store()` picks the backend from PORTPILOT_STORE."""

from __future__ import annotations

from portpilot.store.base import Store, StoreError


def get_store() -> Store:
    from portpilot.config import load_settings

    settings = load_settings()
    if settings.store_backend == "atlas":
        from portpilot.store.atlas import AtlasStore

        if not settings.mongodb_uri:
            raise StoreError("PORTPILOT_STORE=atlas but MONGODB_URI is not set")
        return AtlasStore(settings.mongodb_uri, settings.mongodb_db)
    if settings.store_backend == "memory":
        from portpilot.store.memory import InMemoryStore

        return InMemoryStore()
    raise StoreError(f"unknown PORTPILOT_STORE={settings.store_backend!r}")


__all__ = ["Store", "StoreError", "get_store"]
