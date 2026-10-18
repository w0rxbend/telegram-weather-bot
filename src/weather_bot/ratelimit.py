"""Small in-process rate limiting primitives.

* :class:`Cooldown` – at most one accepted call per key every ``interval`` seconds. Used to
  stop a single user from driving unbounded Open-Meteo / Nominatim traffic and CPU-heavy
  card rendering.
* :class:`MinIntervalGate` – serialises callers so that consecutive calls are at least
  ``interval`` seconds apart (Nominatim's usage policy allows one request per second).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

DEFAULT_MAX_KEYS = 10_000


class Cooldown:
    """Per-key cooldown; the key table is bounded so it cannot grow without limit."""

    def __init__(
        self,
        interval: float,
        *,
        max_keys: int = DEFAULT_MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = interval
        self._max_keys = max_keys
        self._clock = clock
        self._last_accepted: dict[int, float] = {}

    def retry_after(self, key: int) -> float:
        """Seconds to wait before ``key`` may act again; 0.0 means accepted (and recorded)."""
        now = self._clock()
        last = self._last_accepted.get(key)
        if last is not None and now - last < self._interval:
            return self._interval - (now - last)
        self._evict_if_full(now)
        self._last_accepted[key] = now
        return 0.0

    def _evict_if_full(self, now: float) -> None:
        if len(self._last_accepted) < self._max_keys:
            return
        expired = [k for k, t in self._last_accepted.items() if now - t >= self._interval]
        for key in expired:
            del self._last_accepted[key]
        if len(self._last_accepted) >= self._max_keys:  # still full: drop the oldest entry
            del self._last_accepted[next(iter(self._last_accepted))]


class MinIntervalGate:
    """Async gate that spaces consecutive ``wait()`` returns by at least ``interval``."""

    def __init__(self, interval: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._interval = interval
        self._clock = clock
        self._lock = asyncio.Lock()
        self._next_free = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._next_free - self._clock()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_free = self._clock() + self._interval
