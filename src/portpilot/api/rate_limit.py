"""In-memory token-bucket rate limiter keyed by API token (contract: 10 runs/hour)."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Refills continuously at ``capacity / period_s`` tokens/sec; starts full."""

    def __init__(self, capacity: int, period_s: float) -> None:
        self.capacity = capacity
        self.period_s = period_s
        self._rate = capacity / period_s
        self._lock = threading.Lock()
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens = self._tokens.get(key, float(self.capacity))
            last = self._updated.get(key, now)
            tokens = min(self.capacity, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._tokens[key] = tokens
                self._updated[key] = now
                return False
            self._tokens[key] = tokens - 1.0
            self._updated[key] = now
            return True


class RunCreationLimiter(TokenBucket):
    """10 runs per hour per token (contract, lane-p.md)."""

    def __init__(self) -> None:
        super().__init__(capacity=10, period_s=3600.0)
