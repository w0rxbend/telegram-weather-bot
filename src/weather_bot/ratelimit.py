"""Per-user sliding-window rate limiter for expensive actions (card renders).

Every card costs a render and a photo upload, so one user hammering /weather or the refresh
button could otherwise pin the CPU. State is in memory only; it resets on restart.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

DEFAULT_LIMIT = 10  # cards ...
DEFAULT_WINDOW = 60.0  # ... per minute, per user
MAX_TRACKED_USERS = 10_000


class RateLimiter:
    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        window: float = DEFAULT_WINDOW,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[int, deque[float]] = {}

    def allow(self, user_id: int) -> bool:
        """Record an attempt; return False when the user is over the limit."""
        now = self._clock()
        hits = self._hits.setdefault(user_id, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > MAX_TRACKED_USERS:
            self._evict(now)
        return True

    def _evict(self, now: float) -> None:
        for user_id in [u for u, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[user_id]
