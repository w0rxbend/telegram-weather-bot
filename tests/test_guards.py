from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from weather_bot import bot
from weather_bot.ratelimit import RateLimiter


def test_rate_limiter_allows_limit_then_blocks_then_recovers() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=3, window=60, clock=lambda: now[0])
    assert [limiter.allow(1) for _ in range(4)] == [True, True, True, False]
    assert limiter.allow(2)  # other users are unaffected
    now[0] = 61
    assert limiter.allow(1)


def test_rate_limiter_evicts_idle_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("weather_bot.ratelimit.MAX_TRACKED_USERS", 2)
    now = [0.0]
    limiter = RateLimiter(limit=1, window=10, clock=lambda: now[0])
    limiter.allow(1)
    limiter.allow(2)
    now[0] = 20
    limiter.allow(3)
    assert set(limiter._hits) == {3}


def _update(user_id: int = 1, *, callback: bool = False) -> SimpleNamespace:
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(answer=AsyncMock()) if callback else None
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id), effective_message=message, callback_query=query
    )


async def test_guarded_rate_limit_replies_instead_of_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "_card_limiter", RateLimiter(limit=2, window=60))
    handler = AsyncMock()
    guarded = bot._guarded(handler, rate_limited=True)
    update = _update()
    for _ in range(3):
        await guarded(update, SimpleNamespace())
    assert handler.await_count == 2
    update.effective_message.reply_text.assert_awaited_once_with(bot.RATE_LIMITED_TEXT)


async def test_guarded_rate_limit_answers_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "_card_limiter", RateLimiter(limit=1, window=60))
    guarded = bot._guarded(AsyncMock(), rate_limited=True)
    update = _update(callback=True)
    await guarded(update, SimpleNamespace())
    await guarded(update, SimpleNamespace())
    update.callback_query.answer.assert_awaited_once_with(bot.RATE_LIMITED_TEXT, show_alert=True)


async def test_guarded_serializes_updates_of_one_user_but_not_across_users() -> None:
    running = 0
    overall = 0

    async def slow(update: SimpleNamespace, context: SimpleNamespace) -> None:
        nonlocal running, overall
        running += 1
        overall = max(overall, running)
        await asyncio.sleep(0.01)
        running -= 1

    guarded = bot._guarded(slow)
    ctx = SimpleNamespace()
    await asyncio.gather(
        guarded(_update(1), ctx), guarded(_update(1), ctx), guarded(_update(2), ctx)
    )
    assert overall == 2  # user 1 and user 2 overlap ...
    assert running == 0


async def test_guarded_same_user_never_overlaps() -> None:
    active = 0
    violations = 0

    async def handler(update: SimpleNamespace, context: SimpleNamespace) -> None:
        nonlocal active, violations
        active += 1
        violations += active > 1
        await asyncio.sleep(0.01)
        active -= 1

    guarded = bot._guarded(handler)
    await asyncio.gather(*(guarded(_update(7), SimpleNamespace()) for _ in range(5)))
    assert violations == 0
