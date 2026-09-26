"""Private event-loop-on-a-thread helper for wrapping AsyncMongoClient in sync code.

Copied from v0's `store/atlas.py::_LoopThread` (same pattern, same reasoning: one
client / one connection pool lives on a dedicated daemon thread, so sync callers --
including Strands tool calls that may themselves be inside a running event loop --
can drive it with `.result()`.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class _LoopThread:
    """One private asyncio loop on a daemon thread; run coroutines on it from sync code."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self.loop.run_forever, name="portpilot-v2-loop", daemon=True
        )
        self._thread.start()

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def stop(self) -> None:
        async def _cancel_pending() -> None:
            current = asyncio.current_task()
            for task in asyncio.all_tasks():
                if task is not current:
                    task.cancel()

        try:
            self.run(_cancel_pending())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=5)
            self.loop.close()
