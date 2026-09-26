"""Process-wide harness context. Owner: Lead.

Strands tools take only the frozen arguments from plan 4.5 (run_id, attempt,
...). Everything else a tool needs (the store, settings) comes from here.
The orchestrator calls `bind()` once before running any milestone; tests
call `bind(InMemoryStore())`.
"""

from __future__ import annotations

from dataclasses import dataclass

from portpilot.config import Settings, load_settings
from portpilot.store.base import Store


@dataclass
class HarnessContext:
    store: Store
    settings: Settings


_ctx: HarnessContext | None = None


def bind(store: Store, settings: Settings | None = None) -> HarnessContext:
    global _ctx
    _ctx = HarnessContext(store=store, settings=settings or load_settings())
    return _ctx


def ctx() -> HarnessContext:
    if _ctx is None:
        raise RuntimeError("harness context not bound; call portpilot.harness.context.bind()")
    return _ctx
