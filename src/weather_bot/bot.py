"""Telegram handlers.

Flow:
  /start or /setup  -> ask for a location (Telegram "share location" button, or a typed city)
  location message  -> saved per user, reverse-geocoded, infographic sent
  /weather          -> fresh infographic for the saved location
  🔄 Refresh button -> re-fetches and replaces the photo in place
  °C/°F button      -> toggles units and re-renders in place
  any other text    -> one-off infographic for that city (saved location unchanged)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
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

from weather_bot.caption import build_caption
from weather_bot.geocode import Place, reverse_geocode, search_place
from weather_bot.identity import sync_identity
from weather_bot.render import render_card
from weather_bot.weather import Forecast, Units, WeatherError, fetch_forecast

log = logging.getLogger(__name__)

Context = ContextTypes.DEFAULT_TYPE

KEY_LOCATION = "location"
KEY_UNITS = "units"
KEY_AWAITING = "awaiting_location"
KEY_PLACES = "places"
MAX_CACHED_PLACES = 5000

CB_REFRESH = "r"
CB_UNITS = "u"

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
    "<b>Commands</b>\n"
    "/weather – fresh infographic for your saved location\n"
    "/setup – change your saved location\n"
    "/units – switch between °C and °F\n"
    "/help – this message\n\n"
    "You can also type any city name to get its weather without changing your saved location."
)


# --- helpers -----------------------------------------------------------------------------


def _client(context: Context) -> httpx.AsyncClient:
    return context.bot_data["http"]


def _units(context: Context) -> Units:
    return context.user_data.get(KEY_UNITS, "metric")


def _saved_place(context: Context) -> Place | None:
    raw = context.user_data.get(KEY_LOCATION)
    if not raw:
        return None
    return Place(name=raw["name"], latitude=raw["lat"], longitude=raw["lon"])


def _save_place(context: Context, place: Place) -> None:
    context.user_data[KEY_LOCATION] = {
        "name": place.name,
        "lat": place.latitude,
        "lon": place.longitude,
    }
    context.user_data.pop(KEY_AWAITING, None)
    _remember_place(context, place)


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
    name = context.bot_data.get(KEY_PLACES, {}).get(_place_key(lat, lon))
    return Place(name=name or f"{lat:.3f}, {lon:.3f}", latitude=lat, longitude=lon)


def _keyboard(place: Place, units: Units) -> InlineKeyboardMarkup:
    coords = f"{place.latitude:.4f}|{place.longitude:.4f}"
    other = "°F" if units == "metric" else "°C"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"{CB_REFRESH}|{coords}"),
                InlineKeyboardButton(f"Show in {other}", callback_data=f"{CB_UNITS}|{coords}"),
            ]
        ]
    )


def _caption(place: Place, fc: Forecast) -> str:
    return build_caption(place.name, fc)


async def _build_card(context: Context, place: Place, units: Units) -> tuple[bytes, Forecast]:
    forecast = await fetch_forecast(_client(context), place.latitude, place.longitude, units)
    png = await asyncio.to_thread(render_card, forecast, place.name)
    return png, forecast


async def _send_card(
    update: Update, context: Context, place: Place, *, remove_keyboard: bool = False
) -> None:
    message = update.effective_message
    assert message is not None
    units = _units(context)
    await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        png, forecast = await _build_card(context, place, units)
    except WeatherError as exc:
        log.warning("Forecast failed for %s: %s", place, exc)
        await message.reply_text(
            "I couldn't reach the weather service right now. Please try again in a minute.",
            reply_markup=ReplyKeyboardRemove() if remove_keyboard else None,
        )
        return
    if remove_keyboard:
        # A photo cannot carry ReplyKeyboardRemove, so drop the keyboard with a tiny text
        # message first; the photo's inline buttons are what the user keeps.
        await message.reply_text(f"📍 Saved: {place.name}", reply_markup=ReplyKeyboardRemove())
    await message.reply_photo(
        photo=png,
        caption=_caption(place, forecast),
        parse_mode=ParseMode.HTML,
        reply_markup=_keyboard(place, units),
    )


# --- command handlers ---------------------------------------------------------------------


async def cmd_start(update: Update, context: Context) -> None:
    user = update.effective_user
    message = update.effective_message
    assert user is not None and message is not None
    place = _saved_place(context)
    if place:
        await message.reply_text(
            f"Welcome back! Your saved location is <b>{place.name}</b>.\n"
            "Send /weather for a fresh infographic or /setup to change the location.",
            parse_mode=ParseMode.HTML,
        )
        return
    context.user_data[KEY_AWAITING] = True
    await message.reply_text(
        WELCOME.format(name=user.first_name),
        parse_mode=ParseMode.HTML,
        reply_markup=LOCATION_KEYBOARD,
    )


async def cmd_setup(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    context.user_data[KEY_AWAITING] = True
    await message.reply_text(
        "Share your location with the button below, or type a city name.",
        reply_markup=LOCATION_KEYBOARD,
    )


async def cmd_weather(update: Update, context: Context) -> None:
    message = update.effective_message
    assert message is not None
    place = _saved_place(context)
    if place is None:
        context.user_data[KEY_AWAITING] = True
        await message.reply_text(
            "I don't have your location yet. Share it below or type a city name.",
            reply_markup=LOCATION_KEYBOARD,
        )
        return
    await _send_card(update, context, place)


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
    _save_place(context, place)
    await _send_card(update, context, place, remove_keyboard=True)


async def on_text(update: Update, context: Context) -> None:
    message = update.effective_message
    user = update.effective_user
    assert message is not None and message.text is not None
    query = message.text.strip()
    if len(query) < 2 or len(query) > 80:
        await message.reply_text("Please send a city name, or share your location with /setup.")
        return

    await message.chat.send_action(ChatAction.TYPING)
    place = await search_place(_client(context), query, user.language_code if user else None)
    if place is None:
        await message.reply_text(
            f"I couldn't find “{query}”. Try another spelling, or share your location with /setup."
        )
        return

    setting_up = context.user_data.get(KEY_AWAITING) or _saved_place(context) is None
    if setting_up:
        _save_place(context, place)
        await _send_card(update, context, place, remove_keyboard=True)
    else:
        _remember_place(context, place)
        await _send_card(update, context, place)


# --- inline buttons ----------------------------------------------------------------------


def _parse_callback(data: str | None) -> tuple[str, float, float] | None:
    try:
        action, lat, lon = (data or "").split("|")
        return action, float(lat), float(lon)
    except ValueError:
        return None


async def on_callback(update: Update, context: Context) -> None:
    query = update.callback_query
    assert query is not None
    parsed = _parse_callback(query.data)
    if parsed is None or query.message is None:
        await query.answer("This button has expired. Send /weather instead.")
        return
    action, lat, lon = parsed

    if action == CB_UNITS:
        context.user_data[KEY_UNITS] = "imperial" if _units(context) == "metric" else "metric"
    units = _units(context)
    place = _recall_place(context, lat, lon)

    await query.answer("Refreshing…")
    try:
        png, forecast = await _build_card(context, place, units)
    except WeatherError as exc:
        log.warning("Refresh failed for %s: %s", place, exc)
        await query.answer(
            "Weather service is unavailable right now, try again shortly.", show_alert=True
        )
        return

    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=png, caption=_caption(place, forecast), parse_mode=ParseMode.HTML
            ),
            reply_markup=_keyboard(place, units),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        log.warning("Editing media failed (%s); sending a new photo instead", exc)
        await query.message.reply_photo(  # type: ignore[union-attr]
            photo=png,
            caption=_caption(place, forecast),
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard(place, units),
        )


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
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler(["weather", "now", "w"], cmd_weather))
    app.add_handler(CommandHandler("units", cmd_units))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=rf"^({CB_REFRESH}|{CB_UNITS})\|"))
    app.add_error_handler(on_error)
