"""Sliding-window rate limiter keyed by chat/user id.

Rendering and uploading a card is the expensive operation of the bot; without a limit one
chat can pin the CPU by spamming /weather or the refresh button.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable

DEFAULT_LIMIT = 10  # cards ...
DEFAULT_WINDOW = 60.0  # ... per minute per chat
MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        window: float = DEFAULT_WINDOW,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}

    def allow(self, key: Hashable) -> bool:
        """Record an attempt for ``key``; False when it exceeds the budget."""
        now = self._clock()
        if len(self._hits) >= MAX_TRACKED_KEYS:
            self._evict_idle(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _evict_idle(self, now: float) -> None:
        for key in [
            k for k, hits in self._hits.items() if not hits or now - hits[-1] >= self._window
        ]:
            del self._hits[key]
