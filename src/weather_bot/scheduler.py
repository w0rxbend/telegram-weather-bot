"""Background loop that sends scheduled weather cards.

Runs as a plain asyncio task next to the PTB application: every ``INTERVAL`` seconds it
walks all users' persisted data, finds schedule slots that are due in each user's local
time, renders the card for their default location and sends it to the chat where the
schedule was set up. Changes are marked for persistence explicitly because they happen
outside of an update handler.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application

from weather_bot import locations as store
from weather_bot import schedule as sched
from weather_bot.bot import build_card, caption_for, card_keyboard, card_place
from weather_bot.schedule import UserData
from weather_bot.weather import WeatherError

log = logging.getLogger(__name__)

App = Application[Any, Any, Any, Any, Any, Any]

INTERVAL = 30.0
MAX_CONCURRENT_SENDS = 5  # each send fetches a forecast and renders a card


async def scheduler_loop(app: App, interval: float = INTERVAL) -> None:
    log.info("Scheduler started (tick every %.0fs)", interval)
    while True:
        try:
            await tick(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(interval)


async def tick(app: App, now: datetime | None = None) -> int:
    """Send everything that is due; returns the number of users served."""
    now = now or datetime.now(UTC)
    due_users: list[tuple[int, UserData]] = []
    for user_id, data in list(app.user_data.items()):
        due = sched.due_times(data, now)
        if not due:
            continue
        for slot in due:
            sched.mark_sent(data, now, slot)  # mark first: never retry-storm a failing send
        due_users.append((user_id, data))
    if not due_users:
        return 0

    touched = [user_id for user_id, _ in due_users]
    await _persist(app, touched)  # a crash while sending must not re-send after restart
    gate = asyncio.Semaphore(MAX_CONCURRENT_SENDS)
    await asyncio.gather(*(_send_isolated(app, uid, data, gate) for uid, data in due_users))
    await _persist(app, touched)  # _send may have cleared a schedule or updated a time zone
    return len(due_users)


async def _persist(app: App, user_ids: list[int]) -> None:
    app.mark_data_for_update_persistence(user_ids=user_ids)
    await app.update_persistence()


async def _send_isolated(app: App, user_id: int, data: UserData, gate: asyncio.Semaphore) -> None:
    """Bounded and fault-isolated: one failing user must not stop the others' cards."""
    async with gate:
        try:
            await _send(app, user_id, data)
        except Exception:
            log.exception("Scheduled card for user %s failed", user_id)


async def _send(app: App, user_id: int, data: UserData) -> None:
    schedule = sched.get_schedule(data)
    default = store.get_default(data)
    if schedule is None or default is None:
        log.info("User %s has a schedule but no location; disabling it", user_id)
        sched.clear_schedule(data)
        return
    place = card_place(default)
    units = data.get("units", "metric")
    try:
        png, forecast = await build_card(place, units, "weather")
    except WeatherError as exc:
        log.warning("Scheduled card for user %s skipped: %s", user_id, exc)
        return
    sched.update_timezone(data, forecast.timezone)
    try:
        await app.bot.send_photo(
            chat_id=schedule.chat_id,
            photo=png,
            caption=caption_for(place, forecast, "weather"),
            parse_mode=ParseMode.HTML,
            reply_markup=card_keyboard(place, units, "weather"),
        )
    except Forbidden:
        log.info("User %s blocked the bot; schedule removed", user_id)
        sched.clear_schedule(data)
    except TelegramError as exc:
        log.warning("Scheduled send to %s failed: %s", schedule.chat_id, exc)


def start(app: App, interval: float = INTERVAL) -> asyncio.Task:
    return asyncio.create_task(scheduler_loop(app, interval), name="weather-scheduler")


async def stop(task: asyncio.Task | None, on_done: Callable[[], None] | None = None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):  # we cancelled it ourselves
        await task
    if on_done:
        on_done()
