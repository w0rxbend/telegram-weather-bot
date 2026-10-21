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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from weather_bot import health, telemetry
from weather_bot import locations as store
from weather_bot import schedule as sched
from weather_bot.locations import UserData
from weather_bot.runtime import App
from weather_bot.weather import WeatherError

log = logging.getLogger(__name__)

INTERVAL = 30.0
MAX_RETRY_AFTER = 60.0  # longest flood-control wait we will sit out inside a tick
CHAT_GONE = "chat not found"


async def scheduler_loop(
    app: App,
    interval: float = INTERVAL,
    heartbeat: Path | None = None,
) -> None:
    log.info("Scheduler started (tick every %.0fs)", interval)
    while True:
        try:
            await tick(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler tick failed")
        if heartbeat is not None:
            health.beat(heartbeat)
        await asyncio.sleep(interval)


async def tick(app: App, now: datetime | None = None) -> int:
    """Send everything that is due; returns the number of cards sent."""
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
    await _persist(app, touched)  # a crash while sending must not resend after the restart
    sent = 0
    for user_id, data in due_users:
        try:
            await _send(app, user_id, data)
            sent += 1
        except Exception:
            log.exception("Scheduled send for user %s failed", user_id)
    await _persist(app, touched)  # _send may have cleared a schedule or learned a time zone
    return sent


async def _persist(app: App, user_ids: list[int]) -> None:
    app.mark_data_for_update_persistence(user_ids=user_ids)
    await app.update_persistence()


async def _send(app: App, user_id: int, data: UserData) -> None:
    # imported lazily: bot.py imports nothing from here, but keep the dependency one-way
    from weather_bot.bot import _build_card, _caption, _card_place, _keyboard

    schedule = sched.get_schedule(data)
    default = store.get_default(data)
    if schedule is None or default is None:
        log.info("User %s has a schedule but no location; disabling it", user_id)
        sched.clear_schedule(data)
        return
    place = _card_place(default)
    units = data.get("units", "metric")
    try:
        with telemetry.acting_as(user_id):
            png, forecast = await _build_card(place, units, "weather")
    except WeatherError as exc:
        log.warning("Scheduled card for user %s skipped: %s", user_id, exc)
        return
    sched.update_timezone(data, forecast.timezone)
    try:
        await _send_photo(
            app,
            chat_id=schedule.chat_id,
            photo=png,
            caption=_caption(place, forecast, "weather"),
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard(place, units, "weather"),
        )
    except Forbidden:
        log.info("User %s blocked the bot; schedule removed", user_id)
        sched.clear_schedule(data)
    except BadRequest as exc:
        if CHAT_GONE not in str(exc).lower():
            log.warning("Scheduled send for user %s failed: %s", user_id, exc)
            return
        log.info("Chat of user %s no longer exists; schedule removed", user_id)
        sched.clear_schedule(data)
    except TelegramError as exc:
        log.warning("Scheduled send for user %s failed: %s", user_id, exc)


async def _send_photo(app: App, **kwargs: Any) -> None:
    """send_photo, sitting out one Telegram flood-control (429) wait before giving up."""
    try:
        await app.bot.send_photo(**kwargs)
    except RetryAfter as exc:
        delay = exc.retry_after
        seconds = delay.total_seconds() if isinstance(delay, timedelta) else float(delay)
        if seconds > MAX_RETRY_AFTER:
            raise
        log.warning("Flood control: waiting %.0fs before retrying", seconds)
        await asyncio.sleep(seconds)
        await app.bot.send_photo(**kwargs)


def start(
    app: App, interval: float = INTERVAL, heartbeat: Path | None = None
) -> asyncio.Task[None]:
    return asyncio.create_task(scheduler_loop(app, interval, heartbeat), name="weather-scheduler")


async def stop(task: asyncio.Task[None] | None, on_done: Callable[[], None] | None = None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    if on_done:
        on_done()
