"""Update processing: concurrent across users, strictly sequential within one user."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

from telegram import Update
from telegram.ext import BaseUpdateProcessor

DEFAULT_MAX_CONCURRENT_UPDATES = 64


class PerUserUpdateProcessor(BaseUpdateProcessor):
    """Handlers read-modify-write ``user_data``; two parallel updates of one user would race.

    Updates without a user (rare) are not serialised.
    """

    def __init__(self, max_concurrent_updates: int = DEFAULT_MAX_CONCURRENT_UPDATES) -> None:
        super().__init__(max_concurrent_updates)
        self._locks: dict[int, asyncio.Lock] = {}
        self._waiters: dict[int, int] = {}

    async def do_process_update(self, update: object, coroutine: Awaitable[Any]) -> None:
        user = update.effective_user if isinstance(update, Update) else None
        if user is None:
            await coroutine
            return
        key = user.id
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._waiters[key] = self._waiters.get(key, 0) + 1
        try:
            async with lock:
                await coroutine
        finally:
            self._waiters[key] -= 1
            if not self._waiters[key]:
                del self._waiters[key]
                del self._locks[key]

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None
