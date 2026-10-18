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
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from html import escape
from typing import Any, Literal

import httpx
from telegram import (
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
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from weather_bot import locations as store
from weather_bot import runtime
from weather_bot import schedule as sched
from weather_bot.caption import build_caption, build_sun_caption
from weather_bot.geocode import Place, reverse_geocode, search_place
from weather_bot.identity import sync_identity
from weather_bot.locations import MAX_LOCATIONS, SavedLocation
from weather_bot.render import render_card, render_sun_card
from weather_bot.weather import Forecast, Units, WeatherError, fetch_forecast

log = logging.getLogger(__name__)

Context = ContextTypes.DEFAULT_TYPE

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
    "Typing any city name shows its weather without saving it."
)


# --- rate limiting -----------------------------------------------------------------------


def throttled(
    handler: Callable[[Update, Context], Awaitable[None]],
) -> Callable[[Update, Context], Awaitable[None]]:
    """Per-user cooldown for handlers that hit external services or render cards.

    Messages inside the cooldown are dropped silently (answering would amplify a flood);
    callback queries are always answered so the client's spinner stops.
    """

    @wraps(handler)
    async def wrapper(update: Update, context: Context) -> None:
        user = update.effective_user
        if user is not None and runtime.cooldown().retry_after(user.id) > 0:
            log.info("Throttled update %s", update.update_id)
            if update.callback_query is not None:
                await update.callback_query.answer("Easy there – try again in a moment.")
            return
        await handler(update, context)

    return wrapper


# --- helpers -----------------------------------------------------------------------------


def _client(context: Context) -> httpx.AsyncClient:
    return runtime.http()


def _units(context: Context) -> Units:
    return context.user_data.get(KEY_UNITS, "metric")


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
    for loc in store.list_locations(context.user_data):
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
    locs = store.list_locations(context.user_data)
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


async def _build_card(
    place: Place, units: Units, kind: CardKind = "weather"
) -> tuple[bytes, Forecast]:
    forecast = await fetch_forecast(runtime.http(), place.latitude, place.longitude, units)
    render = render_sun_card if kind == "sun" else render_card
    png = await asyncio.to_thread(render, forecast, place.name)
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
        log.warning("Forecast failed for %s: %s", place, exc)
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
    awaiting = context.user_data.pop(KEY_AWAITING, None) or {}
    alias = awaiting.get("alias") if isinstance(awaiting, dict) else None
    try:
        loc, created = store.add_location(context.user_data, place, alias)
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
    context.user_data[KEY_AWAITING] = {"alias": alias or None}


# --- command handlers ---------------------------------------------------------------------


async def cmd_start(update: Update, context: Context) -> None:
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    default = store.get_default(context.user_data)
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
    message = update.effective_message
    assert message is not None
    if len(store.list_locations(context.user_data)) >= MAX_LOCATIONS:
        await message.reply_text(
            f"You already have {MAX_LOCATIONS} locations. Remove one with /remove first."
        )
        return
    alias = _args(context)[:30] or None
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
    message = update.effective_message
    assert message is not None
    if not store.list_locations(context.user_data):
        _ask_for_location(context)
        await message.reply_text(
            "I don't have your location yet. Share it below or type a city name.",
            reply_markup=LOCATION_KEYBOARD,
        )
        return
    query = _args(context)
    loc = store.resolve(context.user_data, query)
    if loc is None:
        await message.reply_text(
            f"No saved location matches “{query}”. Send /locations to see your slots."
        )
        return
    await _send_card(message, context, _card_place(loc), kind=kind)


async def cmd_locations(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    text, keyboard = _locations_view(context)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _slot_arg(context: Context) -> tuple[int | None, str]:
    """Parse ``/cmd N [rest]`` into a 0-based index and the remaining text."""
    args = context.args or []
    if not args or not (args[0].isascii() and args[0].isdigit()):
        return None, " ".join(args[1:])
    return int(args[0]) - 1, " ".join(args[1:]).strip()


async def cmd_default(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    index, _ = _slot_arg(context)
    loc = store.set_default(context.user_data, index) if index is not None else None
    if loc is None:
        await message.reply_text("Usage: /default N – see /locations for slot numbers.")
        return
    await message.reply_text(
        f"⭐ Default is now slot {loc.slot}: <b>{escape(loc.label)}</b>.", parse_mode=ParseMode.HTML
    )


async def cmd_remove(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    index, _ = _slot_arg(context)
    loc = store.remove_location(context.user_data, index) if index is not None else None
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
    message = update.effective_message
    assert message is not None
    index, alias = _slot_arg(context)
    loc = (
        store.rename_location(context.user_data, index, alias[:30])
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
    message = update.effective_message
    assert message is not None
    new_units: Units = "imperial" if _units(context) == "metric" else "metric"
    context.user_data[KEY_UNITS] = new_units
    label = "°F and mph" if new_units == "imperial" else "°C and km/h"
    await message.reply_text(f"Units set to {label}. Send /weather to see it.")


async def cmd_help(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    await message.reply_text(HELP, parse_mode=ParseMode.HTML)


# --- schedule ------------------------------------------------------------------------------


def _schedule_view(
    context: Context, now: datetime | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    current = sched.get_schedule(context.user_data)
    default = store.get_default(context.user_data)
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
    default = store.get_default(context.user_data)
    if default is None:
        return "Save a location first (share it or type a city), then set up the schedule."
    try:
        forecast = await fetch_forecast(
            runtime.http(), default.place.latitude, default.place.longitude
        )
        tz = forecast.timezone
    except WeatherError:
        previous = sched.get_schedule(context.user_data)
        tz = previous.tz if previous else "UTC"
    sched.set_schedule(
        context.user_data, times=times, preset=preset, tz=tz, chat_id=message.chat_id
    )
    return None


async def cmd_schedule(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    arg = _args(context)
    if arg.lower() in {"off", "stop", "disable"}:
        removed = sched.clear_schedule(context.user_data)
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
    query = update.callback_query
    assert query is not None
    message = query.message
    action = (query.data or "").split("|", 1)[-1]
    if message is None:
        await query.answer("This button has expired. Send /schedule instead.")
        return

    if action == "custom":
        context.user_data[sched.KEY_AWAITING_TIMES] = True
        await query.answer()
        await message.reply_text(  # type: ignore[union-attr]
            "Send the times you want, separated by spaces, e.g. <code>7:30 13:00 19:00</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    if action == "off":
        sched.clear_schedule(context.user_data)
        await query.answer("🔕 Turned off")
    elif action == "days":
        result = sched.toggle_days(context.user_data)
        await query.answer("Updated" if result else "Nothing scheduled")
    elif action in sched.PRESETS:
        preset = sched.PRESETS[action]
        error = await _apply_schedule(message, context, times=preset.times, preset=preset.key)  # type: ignore[arg-type]
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
        context.user_data.pop(sched.KEY_AWAITING_TIMES, None)
        await message.reply_text(error)
        return
    view, keyboard = _schedule_view(context)
    await message.reply_text(view, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# --- message handlers --------------------------------------------------------------------


async def on_location(update: Update, context: Context) -> None:
    message = update.effective_message
    user = update.effective_user
    assert message is not None and message.location is not None
    loc = message.location
    await message.chat.send_action(ChatAction.TYPING)
    place = await reverse_geocode(
        _client(context),
        loc.latitude,
        loc.longitude,
        user.language_code if user else None,
        gate=runtime.nominatim_gate(),
    )
    await _save_and_send(message, context, place)


async def on_text(update: Update, context: Context) -> None:
    message = update.effective_message
    user = update.effective_user
    assert message is not None and message.text is not None
    query = message.text.strip()
    if context.user_data.get(sched.KEY_AWAITING_TIMES):
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

    setting_up = bool(context.user_data.get(KEY_AWAITING)) or not store.list_locations(
        context.user_data
    )
    if setting_up:
        await _save_and_send(message, context, place)
    else:
        _remember_place(context, place)
        await _send_card(message, context, place)


# --- inline buttons ----------------------------------------------------------------------


def _parse_callback(data: str | None) -> tuple[str, float, float] | None:
    """Parse ``action|lat|lon``; callback data is client-controlled, so range-check it."""
    try:
        action, lat_text, lon_text = (data or "").split("|")
        lat, lon = float(lat_text), float(lon_text)
    except ValueError:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-MAX_LATITUDE <= lat <= MAX_LATITUDE and -MAX_LONGITUDE <= lon <= MAX_LONGITUDE):
        return None
    return action, lat, lon


def _parse_slot_callback(data: str | None) -> tuple[str, int] | None:
    try:
        action, index = (data or "").split("|")
    except ValueError:
        return None
    if not (index.isascii() and index.isdigit()):
        return None
    return action, int(index)


async def on_card_callback(update: Update, context: Context) -> None:
    """🔄 Refresh and °C/°F buttons under a card."""
    query = update.callback_query
    assert query is not None
    parsed = _parse_callback(query.data)
    if parsed is None or query.message is None:
        await query.answer("This button has expired. Send /weather instead.")
        return
    action, lat, lon = parsed

    if action == CB_UNITS:
        context.user_data[KEY_UNITS] = "imperial" if _units(context) == "metric" else "metric"
    kind: CardKind = "sun" if action == CB_SUN else "weather"
    units = _units(context)
    place = _recall_place(context, lat, lon)

    await query.answer("Refreshing…")
    try:
        png, forecast = await _build_card(place, units, kind)
    except WeatherError as exc:
        log.warning("Refresh failed for %s: %s", place, exc)
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
        await query.message.reply_photo(  # type: ignore[union-attr]
            photo=png,
            caption=_caption(place, forecast, kind),
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard(place, units, kind),
        )


async def on_slot_callback(update: Update, context: Context) -> None:
    """Buttons in the /locations list and the 📍 My locations button under a card."""
    query = update.callback_query
    assert query is not None
    parsed = _parse_slot_callback(query.data)
    message = query.message
    if parsed is None or message is None:
        await query.answer("This button has expired. Send /locations instead.")
        return
    action, index = parsed

    if action == CB_LIST:
        await query.answer()
        text, keyboard = _locations_view(context)
        await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)  # type: ignore[union-attr]
        return

    if action == CB_WEATHER_SLOT:
        locs = store.list_locations(context.user_data)
        if not 0 <= index < len(locs):
            await query.answer("That slot no longer exists.", show_alert=True)
            return
        await query.answer("Fetching…")
        await _send_card(message, context, _card_place(locs[index]))  # type: ignore[arg-type]
        return

    if action == CB_DEFAULT_SLOT:
        loc = store.set_default(context.user_data, index)
        await query.answer(f"⭐ Default: {loc.label}" if loc else "That slot no longer exists.")
    elif action == CB_REMOVE_SLOT:
        loc = store.remove_location(context.user_data, index)
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
    log.exception("Unhandled error while processing update %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Something went wrong. Please try again.")
        except Exception:  # noqa: BLE001 - best effort only
            pass


# --- wiring ------------------------------------------------------------------------------


def make_post_init(
    http_factory: Callable[[], httpx.AsyncClient],
) -> Callable[[Application], Awaitable[None]]:
    async def post_init(app: Application) -> None:
        runtime.set_http(http_factory())
        app.bot_data.pop("http", None)  # left behind by versions < 1.1; never persistable
        await sync_identity(app.bot)

    return post_init


async def post_shutdown(app: Application) -> None:
    try:
        await runtime.http().aclose()
    except RuntimeError:
        pass
    runtime.set_http(None)


def register_handlers(app: Application[Any, Any, Any, Any, Any, Any]) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["add", "setup"], cmd_add))
    app.add_handler(CommandHandler(["weather", "now", "w"], throttled(cmd_weather)))
    app.add_handler(CommandHandler(["sun", "sunset", "sunrise"], throttled(cmd_sun)))
    app.add_handler(CommandHandler(["locations", "list"], cmd_locations))
    app.add_handler(CommandHandler("default", cmd_default))
    app.add_handler(CommandHandler(["remove", "delete"], cmd_remove))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("schedule", throttled(cmd_schedule)))
    app.add_handler(CommandHandler("units", cmd_units))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.LOCATION, throttled(on_location)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, throttled(on_text)))
    app.add_handler(
        CallbackQueryHandler(
            throttled(on_card_callback), pattern=rf"^({CB_REFRESH}|{CB_UNITS}|{CB_SUN})\|"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            throttled(on_slot_callback),
            pattern=rf"^({CB_WEATHER_SLOT}|{CB_DEFAULT_SLOT}|{CB_REMOVE_SLOT}|{CB_LIST})\|",
        )
    )
    app.add_handler(
        CallbackQueryHandler(throttled(on_schedule_callback), pattern=rf"^{CB_SCHEDULE}\|")
    )
    app.add_error_handler(on_error)
