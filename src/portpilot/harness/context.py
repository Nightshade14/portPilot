"""Process-wide harness context. Owner: Lead.

Strands tools take only the frozen arguments from plan 4.5 (run_id, attempt,
...). Everything else a tool needs (the store, settings, the code generator)
comes from here. The orchestrator calls `bind()` once before running any
milestone; tests call `bind(InMemoryStore())`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from portpilot.config import Settings, load_settings
from portpilot.store.base import Store

if TYPE_CHECKING:
    from portpilot.harness.generation import Generator


@dataclass
class HarnessContext:
    store: Store
    settings: Settings
    # None = the default LLM generator. Tests inject a deterministic one.
    generator: Generator | None = None


_ctx: HarnessContext | None = None


def bind(
    store: Store, settings: Settings | None = None, generator: Generator | None = None
) -> HarnessContext:
    global _ctx
    _ctx = HarnessContext(store=store, settings=settings or load_settings(), generator=generator)
    return _ctx


def ctx() -> HarnessContext:
    if _ctx is None:
        raise RuntimeError("harness context not bound; call portpilot.harness.context.bind()")
    return _ctx
