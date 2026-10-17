"""Telegram handlers.

Flow:
  /start            -> ask for a first location (share-location button, or a typed city)
  /add [name]       -> add another location ("speed dial" slot), optionally with a short name
  location message  -> saved as a new slot (first one becomes the default), card sent
  /weather          -> fresh infographic for the default location
  /weather 2|home   -> ... for slot 2, or the slot named/called "home"
  /sun [slot]       -> sunrise / sunset card for the same slots
  /locations        -> list of slots with buttons: get weather, make default, remove
  /default N, /remove N, /rename N name
  🔄 Refresh button -> re-fetches and replaces the photo + caption in place
  °C/°F button      -> toggles units and re-renders in place
  any other text    -> one-off infographic for that city (saved slots unchanged)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
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

CB_REFRESH = "r"
CB_UNITS = "u"
CB_SUN = "s"

CardKind = Literal["weather", "sun"]
CB_WEATHER_SLOT = "w"
CB_DEFAULT_SLOT = "d"
CB_REMOVE_SLOT = "x"
CB_LIST = "l"

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
    "Typing any city name shows its weather without saving it."
)


# --- helpers -----------------------------------------------------------------------------


def _client(context: Context) -> httpx.AsyncClient:
    return context.bot_data["http"]


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
    context: Context, place: Place, units: Units, kind: CardKind = "weather"
) -> tuple[bytes, Forecast]:
    forecast = await fetch_forecast(_client(context), place.latitude, place.longitude, units)
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
        png, forecast = await _build_card(context, place, units, kind)
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
    if not args or not args[0].isdigit():
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


# --- message handlers --------------------------------------------------------------------


async def on_location(update: Update, context: Context) -> None:
    message = update.effective_message
    user = update.effective_user
    assert message is not None and message.location is not None
    loc = message.location
    await message.chat.send_action(ChatAction.TYPING)
    place = await reverse_geocode(
        _client(context), loc.latitude, loc.longitude, user.language_code if user else None
    )
    await _save_and_send(message, context, place)


async def on_text(update: Update, context: Context) -> None:
    message = update.effective_message
    user = update.effective_user
    assert message is not None and message.text is not None
    query = message.text.strip()
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
    try:
        action, lat, lon = (data or "").split("|")
        return action, float(lat), float(lon)
    except ValueError:
        return None


def _parse_slot_callback(data: str | None) -> tuple[str, int] | None:
    try:
        action, index = (data or "").split("|")
        return action, int(index)
    except ValueError:
        return None


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
        png, forecast = await _build_card(context, place, units, kind)
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
        app.bot_data["http"] = http_factory()
        await sync_identity(app.bot)

    return post_init


async def post_shutdown(app: Application) -> None:
    client: httpx.AsyncClient | None = app.bot_data.get("http")
    if client is not None:
        await client.aclose()


def register_handlers(app: Application[Any, Any, Any, Any, Any, Any]) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["add", "setup"], cmd_add))
    app.add_handler(CommandHandler(["weather", "now", "w"], cmd_weather))
    app.add_handler(CommandHandler(["sun", "sunset", "sunrise"], cmd_sun))
    app.add_handler(CommandHandler(["locations", "list"], cmd_locations))
    app.add_handler(CommandHandler("default", cmd_default))
    app.add_handler(CommandHandler(["remove", "delete"], cmd_remove))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("units", cmd_units))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(
        CallbackQueryHandler(on_card_callback, pattern=rf"^({CB_REFRESH}|{CB_UNITS}|{CB_SUN})\|")
    )
    app.add_handler(
        CallbackQueryHandler(
            on_slot_callback,
            pattern=rf"^({CB_WEATHER_SLOT}|{CB_DEFAULT_SLOT}|{CB_REMOVE_SLOT}|{CB_LIST})\|",
        )
    )
    app.add_error_handler(on_error)
