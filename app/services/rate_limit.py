from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    """In-memory per-key sliding window; valid only while the API runs as a single process."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._next_sweep = 0.0

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        if now >= self._next_sweep:
            self._sweep(cutoff)
            self._next_sweep = now + self._window

        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _sweep(self, cutoff: float) -> None:
        # Drop keys without recent hits so memory does not grow with every visitor ever seen.
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
