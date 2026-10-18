"""Background loop that sends scheduled weather cards.

Runs as a plain asyncio task next to the PTB application: every ``INTERVAL`` seconds it
walks all users' persisted data, finds schedule slots that are due in each user's local
time, renders the card for their default location and sends it to the chat where the
schedule was set up. Changes are marked for persistence explicitly because they happen
outside of an update handler.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError

from weather_bot import locations as store
from weather_bot import schedule as sched
from weather_bot.weather import WeatherError

log = logging.getLogger(__name__)

INTERVAL = 30.0


async def scheduler_loop(app, interval: float = INTERVAL) -> None:  # noqa: ANN001 - PTB Application
    log.info("Scheduler started (tick every %.0fs)", interval)
    while True:
        try:
            await tick(app)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive whatever happens
            log.exception("Scheduler tick failed")
        await asyncio.sleep(interval)


async def tick(app, now: datetime | None = None) -> int:  # noqa: ANN001
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


async def _send(app, user_id: int, data) -> None:  # noqa: ANN001
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
        await app.bot.send_photo(
            chat_id=schedule.chat_id,
            photo=png,
            caption=_caption(place, forecast, "weather"),
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard(place, units, "weather"),
        )
    except Forbidden:
        log.info("User %s blocked the bot; schedule removed", user_id)
        sched.clear_schedule(data)
    except TelegramError as exc:
        log.warning("Scheduled send to %s failed: %s", schedule.chat_id, exc)


def start(app, interval: float = INTERVAL) -> asyncio.Task:  # noqa: ANN001
    return asyncio.create_task(scheduler_loop(app, interval), name="weather-scheduler")


async def stop(task: asyncio.Task | None, on_done: Callable[[], None] | None = None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if on_done:
        on_done()
