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

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError

from weather_bot import healthcheck
from weather_bot import locations as store
from weather_bot import schedule as sched
from weather_bot.app_types import App
from weather_bot.weather import WeatherError

log = logging.getLogger(__name__)

INTERVAL = 30.0
MAX_RETRY_AFTER = 30.0  # never stall the whole tick longer than this for one chat


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
        except Exception:  # noqa: BLE001 - keep the loop alive whatever happens
            log.exception("Scheduler tick failed")
        if heartbeat is not None:
            healthcheck.beat(heartbeat)
        await asyncio.sleep(interval)


async def tick(app: App, now: datetime | None = None) -> int:
    """Send everything that is due; returns the number of cards sent."""
    now = now or datetime.now(UTC)
    sent = 0
    touched: list[int] = []
    for user_id, data in list(app.user_data.items()):
        due = sched.due_times(data, now)
        if not due:
            continue
        touched.append(user_id)
        for slot in due:
            sched.mark_sent(data, now, slot)  # mark first: never retry-storm a failing send
        try:
            await _send(app, user_id, data)
            sent += 1
        except Exception:  # noqa: BLE001 - one user's failure must not skip the others
            log.exception("Scheduled send for user %s failed", user_id)
    if touched:
        app.mark_data_for_update_persistence(user_ids=touched)
        await app.update_persistence()
    return sent


async def _send(app: App, user_id: int, data: store.UserData) -> None:
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
        png, forecast = await _build_card(place, units, "weather")
    except WeatherError as exc:
        log.warning("Scheduled card for user %s skipped: %s", user_id, exc)
        return
    sched.update_timezone(data, forecast.timezone)
    try:
        await _send_photo_honouring_flood_control(
            app,
            chat_id=schedule.chat_id,
            photo=png,
            caption=_caption(place, forecast, "weather"),
            reply_markup=_keyboard(place, units, "weather"),
        )
    except Forbidden:
        log.info("User %s blocked the bot; schedule removed", user_id)
        sched.clear_schedule(data)
    except TelegramError as exc:
        log.warning("Scheduled send to %s failed: %s", schedule.chat_id, exc)


async def _send_photo_honouring_flood_control(
    app: App, *, chat_id: int, photo: bytes, caption: str, reply_markup: InlineKeyboardMarkup
) -> None:
    """Send a photo; on Telegram flood control wait the requested time and retry once."""
    kwargs = {
        "chat_id": chat_id,
        "photo": photo,
        "caption": caption,
        "reply_markup": reply_markup,
        "parse_mode": ParseMode.HTML,
    }
    try:
        await app.bot.send_photo(**kwargs)
    except RetryAfter as exc:
        wait = exc.retry_after  # int today, timedelta once PTB_TIMEDELTA becomes the default
        seconds = wait.total_seconds() if isinstance(wait, timedelta) else float(wait)
        delay = min(seconds, MAX_RETRY_AFTER)
        log.warning("Flood control: waiting %.0fs before retrying a scheduled send", delay)
        await asyncio.sleep(delay)
        await app.bot.send_photo(**kwargs)


def start(
    app: App,
    interval: float = INTERVAL,
    heartbeat: Path | None = None,
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
