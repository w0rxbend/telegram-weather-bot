"""Telegram handlers.

Flow:
  /start            -> ask for a first location (share-location button, or a typed city)
  /add [name]       -> add another location ("speed dial" slot), optionally with a short name
  location message  -> saved as a new slot (first one becomes the default), card sent
  /weather          -> fresh infographic for the default location
  /weather 2|home   -> ... for slot 2, or the slot named/called "home"
  /sun [slot]       -> sunrise / sunset card for the same slots
  /schedule         -> automatic cards: presets, custom times, weekdays-only, off
  /locations        -> list of slots with buttons: get weather, make default, remove
  /default N, /remove N, /rename N name
  🔄 Refresh button -> re-fetches and replaces the photo + caption in place
  °C/°F button      -> toggles units and re-renders in place
  any other text    -> one-off infographic for that city (saved slots unchanged)
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import weakref
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from html import escape
from typing import Any, Literal, cast

import httpx
from telegram import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from weather_bot import locations as store
from weather_bot import runtime, telemetry
from weather_bot import schedule as sched
from weather_bot.cache import cached_forecast
from weather_bot.caption import build_caption, build_sun_caption
from weather_bot.geocode import Place, reverse_geocode, search_place
from weather_bot.identity import sync_identity
from weather_bot.locations import MAX_LOCATIONS, SavedLocation
from weather_bot.ratelimit import RateLimiter
from weather_bot.render import render_card, render_stats_card, render_sun_card
from weather_bot.telemetry import Ranked
from weather_bot.weather import Forecast, Units, WeatherError

log = logging.getLogger(__name__)

Context = ContextTypes.DEFAULT_TYPE
App = runtime.App


class UnexpectedUpdateError(RuntimeError):
    """An update lacked a field its handler's filter guarantees."""


KEY_UNITS = "units"
KEY_AWAITING = "awaiting_location"  # dict {"alias": str | None} while /add or /start waits
KEY_PLACES = "places"
MAX_CACHED_PLACES = 5000

MAX_LATITUDE = 90.0
MAX_LONGITUDE = 180.0

CB_REFRESH = "r"
CB_UNITS = "u"
CB_SUN = "s"

CardKind = Literal["weather", "sun"]
CB_WEATHER_SLOT = "w"
CB_DEFAULT_SLOT = "d"
CB_REMOVE_SLOT = "x"
CB_LIST = "l"
CB_SCHEDULE = "sch"

LOCATION_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📍 Share my location", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
    selective=True,
    input_field_placeholder="…or type a city name",
)

WELCOME = (
    "Hi {name}! I turn your location into a weather infographic.\n\n"
    "Tap <b>📍 Share my location</b> below, or type a city name. "
    "After that, send /weather any time for a fresh picture."
)
HELP = (
    "<b>Weather</b>\n"
    "/weather – card for your default location\n"
    "/weather 2 or /weather home – card for slot 2 / the slot called “home”\n"
    "/sun – sunrise &amp; sunset card (also /sun 2, /sunset, /sunrise)\n"
    "/units – switch between °C and °F\n\n"
    "<b>Saved locations (speed dial)</b>\n"
    "/locations – list your slots with quick buttons\n"
    "/add – save another location (share it or type a city)\n"
    "/add home – same, naming the slot “home”\n"
    "/default 2 – make slot 2 the default\n"
    "/rename 2 office – give slot 2 a short name\n"
    "/remove 2 – delete slot 2\n\n"
    "<b>Automatic cards</b>\n"
    "/schedule – pick when I should send the weather by myself "
    "(every morning, 3× a day, hourly 9–21, custom times…)\n"
    "/schedule 7:30 18:00 – custom times · /schedule off – stop\n\n"
    "Typing any city name shows its weather without saving it.\n\n"
    "<i>Privacy: the bot counts your commands and the cities you request, together with your "
    "Telegram id and username, to see how it is used. It never stores message text.</i>"
)


# --- helpers -----------------------------------------------------------------------------


def _message(update: Update) -> Message:
    message = update.effective_message
    if message is None:  # handlers are only registered for message updates
        raise UnexpectedUpdateError("update has no message")
    return message


def _callback(update: Update) -> CallbackQuery:
    query = update.callback_query
    if query is None:
        raise UnexpectedUpdateError("update has no callback query")
    return query


def _query_message(query: CallbackQuery) -> Message | None:
    """The message a button sits on, or None once Telegram no longer exposes it (>48h old)."""
    message = query.message
    if message is None or isinstance(message, InaccessibleMessage):
        return None
    return cast("Message", message)


def _user_data(context: Context) -> dict[str, Any]:
    data = context.user_data
    if data is None:  # None only for updates without a user, which the filters exclude
        raise UnexpectedUpdateError("update has no user")
    return data


def _client(context: Context) -> httpx.AsyncClient:
    return runtime.http()


def _units(context: Context) -> Units:
    units: Units = _user_data(context).get(KEY_UNITS, "metric")
    return units


def _args(context: Context) -> str:
    return " ".join(context.args or []).strip()


def _place_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _remember_place(context: Context, place: Place) -> None:
    """Cache place names by coordinates so refresh buttons never need to geocode again."""
    places: dict[str, str] = context.bot_data.setdefault(KEY_PLACES, {})
    if len(places) >= MAX_CACHED_PLACES:
        for key in list(places)[: len(places) - MAX_CACHED_PLACES + 1]:
            places.pop(key, None)
    places[_place_key(place.latitude, place.longitude)] = place.name


def _recall_place(context: Context, lat: float, lon: float) -> Place:
    for loc in store.list_locations(_user_data(context)):
        if _place_key(loc.place.latitude, loc.place.longitude) == _place_key(lat, lon):
            return Place(name=loc.card_name, latitude=lat, longitude=lon)
    name = context.bot_data.get(KEY_PLACES, {}).get(_place_key(lat, lon))
    return Place(name=name or f"{lat:.3f}, {lon:.3f}", latitude=lat, longitude=lon)


def _card_place(loc: SavedLocation) -> Place:
    return Place(name=loc.card_name, latitude=loc.place.latitude, longitude=loc.place.longitude)


def _keyboard(place: Place, units: Units, kind: CardKind = "weather") -> InlineKeyboardMarkup:
    coords = f"{place.latitude:.4f}|{place.longitude:.4f}"
    other = "°F" if units == "metric" else "°C"
    if kind == "sun":
        rows = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"{CB_SUN}|{coords}"),
                InlineKeyboardButton("🌤 Weather card", callback_data=f"{CB_REFRESH}|{coords}"),
            ]
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"{CB_REFRESH}|{coords}"),
                InlineKeyboardButton(f"Show in {other}", callback_data=f"{CB_UNITS}|{coords}"),
            ],
            [InlineKeyboardButton("🌅 Sun card", callback_data=f"{CB_SUN}|{coords}")],
        ]
    rows[-1].append(InlineKeyboardButton("📍 My locations", callback_data=f"{CB_LIST}|0"))
    return InlineKeyboardMarkup(rows)


def _caption(place: Place, fc: Forecast, kind: CardKind = "weather") -> str:
    if kind == "sun":
        return build_sun_caption(place.name, fc)
    return build_caption(place.name, fc)


def _locations_view(context: Context) -> tuple[str, InlineKeyboardMarkup | None]:
    locs = store.list_locations(_user_data(context))
    if not locs:
        return (
            "You have no saved locations yet. Share one with /add or type a city name.",
            None,
        )
    lines = ["<b>📍 Your locations</b>"]
    rows = []
    for loc in locs:
        star = " ⭐" if loc.is_default else ""
        detail = f" <i>({escape(loc.place.name)})</i>" if loc.alias else ""
        lines.append(f"{loc.slot}. <b>{escape(loc.label)}</b>{detail}{star}")
        rows.append(
            [
                InlineKeyboardButton(
                    f"🌤 {loc.slot} · {loc.label[:20]}",
                    callback_data=f"{CB_WEATHER_SLOT}|{loc.index}",
                ),
                InlineKeyboardButton(
                    "⭐" if not loc.is_default else "✓ default",
                    callback_data=f"{CB_DEFAULT_SLOT}|{loc.index}",
                ),
                InlineKeyboardButton("🗑", callback_data=f"{CB_REMOVE_SLOT}|{loc.index}"),
            ]
        )
    lines.append("")
    lines.append(
        "⭐ = default for /weather. Use <code>/weather 2</code> or <code>/weather home</code> "
        "for a specific slot, /add to save another one."
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


RENDER_CONCURRENCY = os.cpu_count() or 2
_render_slots = asyncio.Semaphore(RENDER_CONCURRENCY)


async def _build_card(
    place: Place, units: Units, kind: CardKind = "weather"
) -> tuple[bytes, Forecast]:
    forecast = await cached_forecast(runtime.http(), place.latitude, place.longitude, units)
    render = render_sun_card if kind == "sun" else render_card
    async with _render_slots:  # Pillow work is CPU-bound: cap it so bursts cannot starve I/O
        png = await asyncio.to_thread(render, forecast, place.name)
    if (usage := runtime.telemetry()) is not None:
        await usage.record_card(place.name, kind)
    return png, forecast


async def _send_card(
    message: Message,
    context: Context,
    place: Place,
    *,
    intro: str | None = None,
    kind: CardKind = "weather",
) -> None:
    """Send a fresh card as a reply to ``message``; ``intro`` also drops the reply keyboard."""
    units = _units(context)
    await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        png, forecast = await _build_card(place, units, kind)
    except WeatherError as exc:
        log.warning("Forecast failed for %s: %s", place.name, exc)
        await message.reply_text(
            "I couldn't reach the weather service right now. Please try again in a minute.",
            reply_markup=ReplyKeyboardRemove() if intro else None,
        )
        return
    if intro:
        # A photo cannot carry ReplyKeyboardRemove, so drop the keyboard with a short text
        # message first; the photo's inline buttons are what the user keeps.
        await message.reply_text(
            intro, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove()
        )
    await message.reply_photo(
        photo=png,
        caption=_caption(place, forecast, kind),
        parse_mode=ParseMode.HTML,
        reply_markup=_keyboard(place, units, kind),
    )


async def _save_and_send(message: Message, context: Context, place: Place) -> None:
    awaiting = _user_data(context).pop(KEY_AWAITING, None) or {}
    alias = awaiting.get("alias") if isinstance(awaiting, dict) else None
    try:
        loc, created = store.add_location(_user_data(context), place, alias)
    except ValueError as exc:
        await message.reply_text(str(exc), reply_markup=ReplyKeyboardRemove())
        return
    _remember_place(context, place)
    verb = "Saved" if created else "Updated"
    intro = f"📍 {verb} slot <b>{loc.slot}</b>: <b>{escape(loc.label)}</b>"
    if loc.is_default:
        intro += " (default)"
    else:
        intro += f"\nUse <code>/weather {loc.slot}</code> or <code>/default {loc.slot}</code>."
    await _send_card(message, context, _card_place(loc), intro=intro)


def _ask_for_location(context: Context, alias: str | None = None) -> None:
    _user_data(context)[KEY_AWAITING] = {"alias": alias or None}


# --- command handlers ---------------------------------------------------------------------


async def cmd_start(update: Update, context: Context) -> None:
    user = update.effective_user
    message = _message(update)
    if user is None:
        return
    default = store.get_default(_user_data(context))
    if default:
        await message.reply_text(
            f"Welcome back! Your default location is <b>{escape(default.label)}</b>.\n"
            "Send /weather for a fresh infographic, /locations to see your slots, "
            "or /add to save another place.",
            parse_mode=ParseMode.HTML,
        )
        return
    _ask_for_location(context)
    await message.reply_text(
        WELCOME.format(name=escape(user.first_name)),
        parse_mode=ParseMode.HTML,
        reply_markup=LOCATION_KEYBOARD,
    )


async def cmd_add(update: Update, context: Context) -> None:
    message = _message(update)
    if len(store.list_locations(_user_data(context))) >= MAX_LOCATIONS:
        await message.reply_text(
            f"You already have {MAX_LOCATIONS} locations. Remove one with /remove first."
        )
        return
    alias = store.clean_alias(_args(context))
    _ask_for_location(context, alias)
    hint = f" It will be saved as “{alias}”." if alias else ""
    await message.reply_text(
        f"Share the location with the button below, or type a city name.{hint}",
        reply_markup=LOCATION_KEYBOARD,
    )


async def cmd_weather(update: Update, context: Context) -> None:
    await _send_for_slot(update, context, "weather")


async def cmd_sun(update: Update, context: Context) -> None:
    await _send_for_slot(update, context, "sun")


async def _send_for_slot(update: Update, context: Context, kind: CardKind) -> None:
    message = _message(update)
    if not store.list_locations(_user_data(context)):
        _ask_for_location(context)
        await message.reply_text(
            "I don't have your location yet. Share it below or type a city name.",
            reply_markup=LOCATION_KEYBOARD,
        )
        return
    query = _args(context)
    loc = store.resolve(_user_data(context), query)
    if loc is None:
        await message.reply_text(
            f"No saved location matches “{query}”. Send /locations to see your slots."
        )
        return
    await _send_card(message, context, _card_place(loc), kind=kind)


async def cmd_locations(update: Update, context: Context) -> None:
    message = _message(update)
    text, keyboard = _locations_view(context)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _slot_arg(context: Context) -> tuple[int | None, str]:
    """Parse ``/cmd N [rest]`` into a 0-based index and the remaining text."""
    args = context.args or []
    if not args or not (args[0].isascii() and args[0].isdigit()):
        return None, " ".join(args[1:])
    return int(args[0]) - 1, " ".join(args[1:]).strip()


async def cmd_default(update: Update, context: Context) -> None:
    message = _message(update)
    index, _ = _slot_arg(context)
    loc = store.set_default(_user_data(context), index) if index is not None else None
    if loc is None:
        await message.reply_text("Usage: /default N – see /locations for slot numbers.")
        return
    await message.reply_text(
        f"⭐ Default is now slot {loc.slot}: <b>{escape(loc.label)}</b>.", parse_mode=ParseMode.HTML
    )


async def cmd_remove(update: Update, context: Context) -> None:
    message = _message(update)
    index, _ = _slot_arg(context)
    loc = store.remove_location(_user_data(context), index) if index is not None else None
    if loc is None:
        await message.reply_text("Usage: /remove N – see /locations for slot numbers.")
        return
    text, keyboard = _locations_view(context)
    await message.reply_text(
        f"🗑 Removed <b>{escape(loc.label)}</b>.\n\n{text}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def cmd_rename(update: Update, context: Context) -> None:
    message = _message(update)
    index, alias = _slot_arg(context)
    loc = (
        store.rename_location(_user_data(context), index, alias)
        if index is not None and alias
        else None
    )
    if loc is None:
        await message.reply_text("Usage: /rename N new-name – e.g. /rename 2 office")
        return
    await message.reply_text(
        f"✏️ Slot {loc.slot} is now <b>{escape(loc.label)}</b>.", parse_mode=ParseMode.HTML
    )


async def cmd_units(update: Update, context: Context) -> None:
    message = _message(update)
    new_units: Units = "imperial" if _units(context) == "metric" else "metric"
    _user_data(context)[KEY_UNITS] = new_units
    label = "°F and mph" if new_units == "imperial" else "°C and km/h"
    await message.reply_text(f"Units set to {label}. Send /weather to see it.")


async def cmd_help(update: Update, context: Context) -> None:
    message = _message(update)
    await message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_export(update: Update, context: Context) -> None:
    """Raw event log as CSV (time, user id, username, event, city) for the operator."""
    user = update.effective_user
    usage = runtime.telemetry()
    if user is None or usage is None or not runtime.is_admin(user.id):
        return
    csv_text = await usage.export_csv()
    await _message(update).reply_document(
        document=csv_text.encode(),
        filename=f"usage-{datetime.now(UTC):%Y%m%d-%H%M}.csv",
    )


def _format_ranking(title: str, rows: list[Ranked]) -> str:
    lines = [f"{index}. {escape(row.label)} – {row.count}" for index, row in enumerate(rows, 1)]
    return f"<b>{title}</b>\n" + ("\n".join(lines) if lines else "–")


async def cmd_stats(update: Update, context: Context) -> None:
    """Usage report for the operator; silently ignored for everybody else."""
    user = update.effective_user
    usage = runtime.telemetry()
    if user is None or usage is None or not runtime.is_admin(user.id):
        return
    report = await usage.report()
    message = _message(update)
    async with _render_slots:
        png = await asyncio.to_thread(render_stats_card, report, datetime.now(UTC))
    await message.reply_photo(photo=png)
    await message.reply_text(
        f"<b>Usage</b>: {report.users} users · {report.events} actions · {report.cards} cards\n\n"
        + "\n\n".join(
            (
                _format_ranking("Top users (actions)", report.top_users),
                _format_ranking("Top cities (cards)", report.top_cities),
                _format_ranking("Top actions", report.top_events),
            )
        ),
        parse_mode=ParseMode.HTML,
    )


# --- schedule ------------------------------------------------------------------------------


def _schedule_view(
    context: Context, now: datetime | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    current = sched.get_schedule(_user_data(context))
    default = store.get_default(_user_data(context))
    lines = ["<b>⏰ Automatic weather cards</b>"]
    if current:
        lines.append(f"Current: {escape(current.describe())}")
        nxt = current.next_run(now or datetime.now(UTC))
        if nxt:
            lines.append(f"Next card: <b>{nxt.strftime('%a %H:%M')}</b>")
    else:
        lines.append("Currently off.")
    if default:
        lines.append(f"Location: <b>{escape(default.label)}</b> (your default slot)")
    lines.append("")
    lines.append("Pick a preset, or send custom times like <code>/schedule 7:30 18:00</code>.")

    rows = [
        [
            InlineKeyboardButton(
                ("✓ " if current and current.preset == p.key else "") + p.label,
                callback_data=f"{CB_SCHEDULE}|{p.key}",
            )
        ]
        for p in sched.PRESETS.values()
    ]
    rows.append([InlineKeyboardButton("✏️ Custom times…", callback_data=f"{CB_SCHEDULE}|custom")])
    if current:
        days_label = "📅 Switch to every day" if current.days == "weekdays" else "📅 Weekdays only"
        rows.append(
            [
                InlineKeyboardButton(days_label, callback_data=f"{CB_SCHEDULE}|days"),
                InlineKeyboardButton("🔕 Turn off", callback_data=f"{CB_SCHEDULE}|off"),
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _apply_schedule(
    message: Message, context: Context, *, times: list[str] | tuple[str, ...], preset: str
) -> str | None:
    """Store a schedule for this user/chat. Returns an error message, or None on success."""
    default = store.get_default(_user_data(context))
    if default is None:
        return "Save a location first (share it or type a city), then set up the schedule."
    try:
        forecast = await cached_forecast(
            runtime.http(), default.place.latitude, default.place.longitude
        )
        tz = forecast.timezone
    except WeatherError:
        previous = sched.get_schedule(_user_data(context))
        tz = previous.tz if previous else "UTC"
    sched.set_schedule(
        _user_data(context), times=times, preset=preset, tz=tz, chat_id=message.chat_id
    )
    return None


async def cmd_schedule(update: Update, context: Context) -> None:
    message = _message(update)
    arg = _args(context)
    if arg.lower() in {"off", "stop", "disable"}:
        removed = sched.clear_schedule(_user_data(context))
        await message.reply_text(
            "🔕 Automatic cards are off." if removed else "Nothing was scheduled."
        )
        return
    if arg:
        try:
            times = sched.parse_times(arg)
        except ValueError as exc:
            await message.reply_text(str(exc))
            return
        error = await _apply_schedule(message, context, times=times, preset="custom")
        if error:
            await message.reply_text(error)
            return
    text, keyboard = _schedule_view(context)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def on_schedule_callback(update: Update, context: Context) -> None:
    query = _callback(update)
    message = _query_message(query)
    action = (query.data or "").split("|", 1)[-1]
    if message is None:
        await query.answer("This button has expired. Send /schedule instead.")
        return

    if action == "custom":
        _user_data(context)[sched.KEY_AWAITING_TIMES] = True
        await query.answer()
        await message.reply_text(
            "Send the times you want, separated by spaces, e.g. <code>7:30 13:00 19:00</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    if action == "off":
        sched.clear_schedule(_user_data(context))
        await query.answer("🔕 Turned off")
    elif action == "days":
        result = sched.toggle_days(_user_data(context))
        await query.answer("Updated" if result else "Nothing scheduled")
    elif action in sched.PRESETS:
        preset = sched.PRESETS[action]
        error = await _apply_schedule(message, context, times=preset.times, preset=preset.key)
        if error:
            await query.answer(error, show_alert=True)
            return
        await query.answer("✓ Scheduled")
    else:
        await query.answer()
        return

    text, keyboard = _schedule_view(context)
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def _on_custom_times(message: Message, context: Context, text: str) -> None:
    try:
        times = sched.parse_times(text)
    except ValueError as exc:
        await message.reply_text(f"{exc}\nOr send /schedule off to cancel.")
        return
    error = await _apply_schedule(message, context, times=times, preset="custom")
    if error:
        _user_data(context).pop(sched.KEY_AWAITING_TIMES, None)
        await message.reply_text(error)
        return
    view, keyboard = _schedule_view(context)
    await message.reply_text(view, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# --- message handlers --------------------------------------------------------------------


async def on_location(update: Update, context: Context) -> None:
    message = _message(update)
    user = update.effective_user
    loc = message.location
    if loc is None:
        return
    await message.chat.send_action(ChatAction.TYPING)
    place = await reverse_geocode(
        _client(context), loc.latitude, loc.longitude, user.language_code if user else None
    )
    await _save_and_send(message, context, place)


async def on_text(update: Update, context: Context) -> None:
    message = _message(update)
    user = update.effective_user
    if message.text is None:
        return
    query = message.text.strip()
    if _user_data(context).get(sched.KEY_AWAITING_TIMES):
        await _on_custom_times(message, context, query)
        return
    if len(query) < 2 or len(query) > 80:
        await message.reply_text("Please send a city name, or share your location with /add.")
        return

    await message.chat.send_action(ChatAction.TYPING)
    place = await search_place(_client(context), query, user.language_code if user else None)
    if place is None:
        await message.reply_text(
            f"I couldn't find “{query}”. Try another spelling, or share your location with /add."
        )
        return

    setting_up = bool(_user_data(context).get(KEY_AWAITING)) or not store.list_locations(
        _user_data(context)
    )
    if setting_up:
        await _save_and_send(message, context, place)
    else:
        _remember_place(context, place)
        await _send_card(message, context, place)


# --- inline buttons ----------------------------------------------------------------------


def _parse_callback(data: str | None) -> tuple[str, float, float] | None:
    try:
        action, lat, lon = (data or "").split("|")
        latitude, longitude = float(lat), float(lon)
    except ValueError:
        return None
    # callback_data is client-controlled; reject NaN/inf and out-of-range coordinates
    if not (
        -MAX_LATITUDE <= latitude <= MAX_LATITUDE and -MAX_LONGITUDE <= longitude <= MAX_LONGITUDE
    ):
        return None
    return action, latitude, longitude


def _parse_slot_callback(data: str | None) -> tuple[str, int] | None:
    try:
        action, index = (data or "").split("|")
        return action, int(index)
    except ValueError:
        return None


async def on_card_callback(update: Update, context: Context) -> None:
    """🔄 Refresh and °C/°F buttons under a card."""
    query = _callback(update)
    parsed = _parse_callback(query.data)
    message = _query_message(query)
    if parsed is None or message is None:
        await query.answer("This button has expired. Send /weather instead.")
        return
    action, lat, lon = parsed

    if action == CB_UNITS:
        _user_data(context)[KEY_UNITS] = "imperial" if _units(context) == "metric" else "metric"
    kind: CardKind = "sun" if action == CB_SUN else "weather"
    units = _units(context)
    place = _recall_place(context, lat, lon)

    await query.answer("Refreshing…")
    try:
        png, forecast = await _build_card(place, units, kind)
    except WeatherError as exc:
        log.warning("Refresh failed for %s: %s", place.name, exc)
        await query.answer(
            "Weather service is unavailable right now, try again shortly.", show_alert=True
        )
        return

    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=png, caption=_caption(place, forecast, kind), parse_mode=ParseMode.HTML
            ),
            reply_markup=_keyboard(place, units, kind),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        log.warning("Editing media failed (%s); sending a new photo instead", exc)
        await message.reply_photo(
            photo=png,
            caption=_caption(place, forecast, kind),
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard(place, units, kind),
        )


async def on_slot_callback(update: Update, context: Context) -> None:
    """Buttons in the /locations list and the 📍 My locations button under a card."""
    query = _callback(update)
    parsed = _parse_slot_callback(query.data)
    message = _query_message(query)
    if parsed is None or message is None:
        await query.answer("This button has expired. Send /locations instead.")
        return
    action, index = parsed

    if action == CB_LIST:
        await query.answer()
        text, keyboard = _locations_view(context)
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    if action == CB_WEATHER_SLOT:
        locs = store.list_locations(_user_data(context))
        if not 0 <= index < len(locs):
            await query.answer("That slot no longer exists.", show_alert=True)
            return
        await query.answer("Fetching…")
        await _send_card(message, context, _card_place(locs[index]))
        return

    if action == CB_DEFAULT_SLOT:
        loc = store.set_default(_user_data(context), index)
        await query.answer(f"⭐ Default: {loc.label}" if loc else "That slot no longer exists.")
    elif action == CB_REMOVE_SLOT:
        loc = store.remove_location(_user_data(context), index)
        await query.answer(f"🗑 Removed {loc.label}" if loc else "That slot no longer exists.")
    else:
        await query.answer()
        return

    text, keyboard = _locations_view(context)
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def on_error(update: object, context: Context) -> None:
    update_id = update.update_id if isinstance(update, Update) else None
    user_id = (
        update.effective_user.id if isinstance(update, Update) and update.effective_user else None
    )
    # Never log the update itself: it carries message text and shared coordinates.
    log.error("Unhandled error in update %s (user %s)", update_id, user_id, exc_info=context.error)
    if not isinstance(update, Update):
        return
    try:
        if update.callback_query:
            await update.callback_query.answer("Something went wrong. Please try again.")
        elif update.effective_message:
            await update.effective_message.reply_text("Something went wrong. Please try again.")
    except TelegramError as exc:
        log.warning("Could not report the error to user %s: %s", user_id, exc)


# --- wiring ------------------------------------------------------------------------------


def make_post_init(
    http_factory: Callable[[], httpx.AsyncClient],
) -> Callable[[App], Awaitable[None]]:
    async def post_init(app: App) -> None:
        runtime.set_http(http_factory())
        app.bot_data.pop("http", None)  # left behind by versions < 1.1; never persistable
        await sync_identity(app.bot)

    return post_init


async def post_shutdown(app: App) -> None:
    with contextlib.suppress(RuntimeError):
        await runtime.http().aclose()
    runtime.set_http(None)


_user_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()
_card_limiter = RateLimiter()
RATE_LIMITED_TEXT = "You're asking for cards too fast. Please wait a minute and try again."

Handler = Callable[[Update, Context], Coroutine[Any, Any, None]]


def _guarded(callback: Handler, *, rate_limited: bool = False) -> Handler:
    """Run ``callback`` one update at a time per user, optionally rate limited.

    PTB runs updates concurrently; two quick taps from one user would otherwise interleave
    their read-modify-write of ``user_data`` (slots, schedule).
    """

    @functools.wraps(callback)
    async def wrapper(update: Update, context: Context) -> None:
        user = update.effective_user
        if user is None:
            return
        if rate_limited and not _card_limiter.allow(user.id):
            if update.callback_query:
                await update.callback_query.answer(RATE_LIMITED_TEXT, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(RATE_LIMITED_TEXT)
            return
        if (usage := runtime.telemetry()) is not None:
            await usage.record_event(user.id, callback.__name__, user.username, user.language_code)
        lock = _user_locks.get(user.id)
        if lock is None:
            lock = _user_locks[user.id] = asyncio.Lock()
        async with lock:
            with telemetry.acting_as(user.id):
                await callback(update, context)

    return wrapper


def register_handlers(app: App) -> None:
    commands: list[tuple[str | list[str], Handler]] = [
        ("start", _guarded(cmd_start)),
        (["add", "setup"], _guarded(cmd_add)),
        (["weather", "now", "w"], _guarded(cmd_weather, rate_limited=True)),
        (["sun", "sunset", "sunrise"], _guarded(cmd_sun, rate_limited=True)),
        (["locations", "list"], _guarded(cmd_locations)),
        ("default", _guarded(cmd_default)),
        (["remove", "delete"], _guarded(cmd_remove)),
        ("rename", _guarded(cmd_rename)),
        ("schedule", _guarded(cmd_schedule)),
        ("units", _guarded(cmd_units)),
        ("help", cmd_help),
    ]
    for names, callback in commands:
        # new messages only: edited messages and channel posts have no usable user_data
        app.add_handler(CommandHandler(names, callback, filters=filters.UpdateType.MESSAGE))
    admin_ids = runtime.admin_ids()
    if admin_ids:
        # not in /help or the command menu, and not even matched for anyone but the admins
        admin_filter = filters.UpdateType.MESSAGE & filters.User(user_id=admin_ids)
        app.add_handler(CommandHandler("stats", cmd_stats, filters=admin_filter))
        app.add_handler(CommandHandler("export", cmd_export, filters=admin_filter))
    app.add_handler(
        MessageHandler(
            filters.LOCATION & filters.UpdateType.MESSAGE, _guarded(on_location, rate_limited=True)
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
            _guarded(on_text, rate_limited=True),
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            _guarded(on_card_callback, rate_limited=True),
            pattern=rf"^({CB_REFRESH}|{CB_UNITS}|{CB_SUN})\|",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            _guarded(on_slot_callback, rate_limited=True),
            pattern=rf"^({CB_WEATHER_SLOT}|{CB_DEFAULT_SLOT}|{CB_REMOVE_SLOT}|{CB_LIST})\|",
        )
    )
    app.add_handler(
        CallbackQueryHandler(_guarded(on_schedule_callback), pattern=rf"^{CB_SCHEDULE}\|")
    )
    app.add_error_handler(on_error)
