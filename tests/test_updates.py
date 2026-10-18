from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from telegram import Chat, Message, Update, User

from weather_bot.updates import PerUserUpdateProcessor


def update_for(user_id: int) -> Update:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, first_name="U", is_bot=False),
        text="x",
    )
    return Update(update_id=1, message=message)


async def test_same_user_updates_never_overlap() -> None:
    processor = PerUserUpdateProcessor()
    running = 0
    peak = 0

    async def handler() -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    await asyncio.gather(*(processor.process_update(update_for(1), handler()) for _ in range(5)))
    assert peak == 1
    assert not processor._locks  # noqa: SLF001 - bookkeeping must not leak per-user state


async def test_different_users_run_concurrently() -> None:
    processor = PerUserUpdateProcessor()
    running = 0
    peak = 0

    async def handler() -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    await asyncio.gather(*(processor.process_update(update_for(i), handler()) for i in range(4)))
    assert peak == 4


async def test_failure_releases_the_lock() -> None:
    processor = PerUserUpdateProcessor()

    async def boom() -> None:
        raise RuntimeError("x")

    async def ok() -> None:
        return None

    with contextlib.suppress(RuntimeError):
        await processor.process_update(update_for(1), boom())
    await asyncio.wait_for(processor.process_update(update_for(1), ok()), timeout=1)
