from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from weather_bot import bot, runtime
from weather_bot.ratelimit import Cooldown, MinIntervalGate


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_cooldown_blocks_repeat_calls_until_interval_passes() -> None:
    clock = FakeClock()
    cooldown = Cooldown(2.0, clock=clock)
    assert cooldown.retry_after(1) == 0.0
    clock.now += 0.5
    assert cooldown.retry_after(1) == pytest.approx(1.5)
    assert cooldown.retry_after(2) == 0.0  # other users are independent
    clock.now += 1.5
    assert cooldown.retry_after(1) == 0.0


def test_cooldown_table_is_bounded() -> None:
    clock = FakeClock()
    cooldown = Cooldown(60.0, max_keys=3, clock=clock)
    for user_id in range(10):
        clock.now += 1
        cooldown.retry_after(user_id)
    assert len(cooldown._last_accepted) <= 3


async def test_gate_spaces_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = MinIntervalGate(0.05)
    started = asyncio.get_running_loop().time()
    await asyncio.gather(gate.wait(), gate.wait(), gate.wait())
    assert asyncio.get_running_loop().time() - started >= 0.09


def _update(user_id: int, *, callback: bool = False) -> SimpleNamespace:
    query = SimpleNamespace(answer=AsyncMock()) if callback else None
    return SimpleNamespace(
        update_id=1, effective_user=SimpleNamespace(id=user_id), callback_query=query
    )


async def test_throttled_drops_second_message_inside_cooldown() -> None:
    inner = AsyncMock()
    handler = bot.throttled(inner)
    await handler(_update(7), SimpleNamespace())
    await handler(_update(7), SimpleNamespace())
    assert inner.await_count == 1


async def test_throttled_always_answers_callback_queries() -> None:
    inner = AsyncMock()
    handler = bot.throttled(inner)
    await handler(_update(7, callback=True), SimpleNamespace())
    blocked = _update(7, callback=True)
    await handler(blocked, SimpleNamespace())
    assert inner.await_count == 1
    blocked.callback_query.answer.assert_awaited_once()


async def test_throttled_is_per_user() -> None:
    inner = AsyncMock()
    handler = bot.throttled(inner)
    await handler(_update(1), SimpleNamespace())
    await handler(_update(2), SimpleNamespace())
    assert inner.await_count == 2
    assert runtime.cooldown() is runtime.cooldown()
