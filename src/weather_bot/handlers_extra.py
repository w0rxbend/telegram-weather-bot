"""Handlers beyond the core card flow: language, air, rain alerts, compare, best hour, inline.

Kept out of ``bot.py`` so that module stays about the card flow. These handlers reuse its
helpers; ``bot.register_handlers`` imports this module lazily to keep the dependency one-way.
"""

from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.constants import ChatType, ParseMode

from weather_bot import alerts, planner
from weather_bot import locations as store
from weather_bot.airquality import fetch_air_quality
from weather_bot.bot import (
    MAX_QUERY_LENGTH,
    Context,
    _args,
    _callback,
    _client,
    _lang,
    _message,
    _query_message,
    _units,
    _user_data,
)
from weather_bot.cache import cached_forecast
from weather_bot.caption import build_caption, weather_emoji
from weather_bot.geocode import Place, search_place
from weather_bot.i18n import ACTIVITY_NAMES, KEY_LANG, SUPPORTED, Lang, describe_weather, tr
from weather_bot.weather import Forecast, WeatherError, describe

log = logging.getLogger(__name__)

CB_LANG = "lang"
INLINE_CACHE_SECONDS = 300
INLINE_OUTLOOK_DAYS = 3
LANGUAGE_NAMES: dict[str, str] = {"en": "English", "uk": "Українська"}


# --- /lang ---------------------------------------------------------------------------------


async def cmd_lang(update: Update, context: Context) -> None:
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(LANGUAGE_NAMES[code], callback_data=f"{CB_LANG}|{code}")]
            for code in SUPPORTED
        ]
    )
    await _message(update).reply_text(tr(_lang(context), "lang_prompt"), reply_markup=keyboard)


async def on_lang_callback(update: Update, context: Context) -> None:
    query = _callback(update)
    code = (query.data or "").split("|", 1)[-1]
    message = _query_message(query)
    if code not in SUPPORTED:  # callback_data is client-controlled
        await query.answer()
        return
    chosen: Lang = "uk" if code == "uk" else "en"
    _user_data(context)[KEY_LANG] = chosen
    await query.answer()
    if message is not None:
        await message.edit_text(tr(chosen, "lang_set"))


# --- /air ----------------------------------------------------------------------------------


def _saved_place(context: Context, query: str) -> Place | None:
    loc = store.resolve(_user_data(context), query)
    if loc is None:
        return None
    return Place(name=loc.card_name, latitude=loc.place.latitude, longitude=loc.place.longitude)


async def cmd_air(update: Update, context: Context) -> None:
    message, lang = _message(update), _lang(context)
    place = _saved_place(context, _args(context))
    if place is None:
        await message.reply_text(tr(lang, "no_location"))
        return
    try:
        air = await fetch_air_quality(_client(context), place.latitude, place.longitude)
    except WeatherError as exc:
        log.warning("Air quality failed: %s", exc)
        await message.reply_text(tr(lang, "air_unavailable"))
        return
    await message.reply_text(
        f"🌬 <b>{tr(lang, 'air_title')}</b> · {escape(place.name)}\n"
        f"{air.label(lang)} (AQI {air.aqi})\n"
        f"PM2.5 {air.pm2_5:.0f} µg/m³ · PM10 {air.pm10:.0f} µg/m³",
        parse_mode=ParseMode.HTML,
    )


# --- /alerts -------------------------------------------------------------------------------


async def cmd_alerts(update: Update, context: Context) -> None:
    message, lang = _message(update), _lang(context)
    chat = update.effective_chat
    if chat is None or chat.type != ChatType.PRIVATE:
        await message.reply_text(tr(lang, "alerts_private_only"))
        return
    data = _user_data(context)
    argument = _args(context).lower()
    turn_on = argument == "on" or (argument != "off" and alerts.chat_id_for(data) is None)
    if not turn_on:
        alerts.disable(data)
        await message.reply_text(tr(lang, "alerts_off"))
        return
    if store.get_default(data) is None:
        await message.reply_text(tr(lang, "alerts_need_location"))
        return
    alerts.enable(data, chat.id)
    await message.reply_text(tr(lang, "alerts_on"))


# --- /compare ------------------------------------------------------------------------------


async def _forecast_for(
    context: Context, text: str, language: str | None
) -> tuple[Place, Forecast]:
    place = await search_place(_client(context), text, language)
    if place is None:
        raise LookupError(text)
    forecast = await cached_forecast(
        _client(context), place.latitude, place.longitude, _units(context)
    )
    return place, forecast


def _compare_line(place: Place, fc: Forecast, lang: Lang) -> str:
    today = fc.today
    return (
        f"{weather_emoji(fc.weather_code, fc.is_day)} <b>{escape(place.name)}</b>\n"
        f"   {round(fc.temperature)}{fc.temp_unit} · "
        f"{describe_weather(lang, fc.weather_code, describe(fc.weather_code))}\n"
        f"   ⬆️ {round(today.t_max)}° ⬇️ {round(today.t_min)}° · "
        f"☔ {today.precipitation_probability_max}% · 💨 {fc.wind_speed:.0f} {fc.speed_unit}"
    )


async def cmd_compare(update: Update, context: Context) -> None:
    message, lang = _message(update), _lang(context)
    names = planner.split_places(_args(context))
    if not (
        planner.COMPARE_MIN_PLACES <= len(names) <= planner.COMPARE_MAX_PLACES
        and all(2 <= len(name) <= MAX_QUERY_LENGTH for name in names)
    ):
        await message.reply_text(tr(lang, "compare_usage"))
        return
    code = update.effective_user.language_code if update.effective_user else None
    results = await asyncio.gather(
        *(_forecast_for(context, name, code) for name in names), return_exceptions=True
    )
    lines = [f"🆚 <b>{tr(lang, 'compare_title')}</b>"]
    for name, result in zip(names, results, strict=True):
        if isinstance(result, LookupError):
            lines.append(escape(tr(lang, "cant_find", query=name[:MAX_QUERY_LENGTH])))
        elif isinstance(result, WeatherError):
            lines.append(escape(tr(lang, "weather_down")))
        elif isinstance(result, BaseException):
            raise result
        else:
            lines.append(_compare_line(*result, lang))
    await message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)


# --- /best ---------------------------------------------------------------------------------


async def cmd_best(update: Update, context: Context) -> None:
    message, lang = _message(update), _lang(context)
    words = _args(context).split(maxsplit=1)
    activity = planner.parse_activity(words[0]) if words else None
    if activity is None:
        await message.reply_text(tr(lang, "best_usage"))
        return
    place = _saved_place(context, words[1] if len(words) > 1 else "")
    if place is None:
        await message.reply_text(tr(lang, "no_location"))
        return
    try:
        fc = await cached_forecast(
            _client(context), place.latitude, place.longitude, _units(context)
        )
    except WeatherError as exc:
        log.warning("Forecast for /best failed: %s", exc)
        await message.reply_text(tr(lang, "weather_down"))
        return
    window = planner.best_window(fc, activity)
    if window is None:
        await message.reply_text(tr(lang, "best_none"))
        return
    same_day = window.start.date() == fc.observed_at.date()
    await message.reply_text(
        tr(
            lang,
            "best_result",
            emoji=activity.emoji,
            activity=ACTIVITY_NAMES[activity.key][lang],
            day=tr(lang, "day_today" if same_day else "day_tomorrow"),
            start=window.start.strftime("%H:%M"),
            end=window.end.strftime("%H:%M"),
            temp=f"{window.temperature:.0f}{fc.temp_unit}",
            rain=window.rain,
            place=escape(place.name),
        ),
        parse_mode=ParseMode.HTML,
    )


# --- inline mode ---------------------------------------------------------------------------


async def on_inline_query(update: Update, context: Context) -> None:
    """``@bot Kyiv`` in any chat: offer the forecast as a ready-to-send message."""
    inline = update.inline_query
    user = update.effective_user
    if inline is None or user is None:
        return
    text = inline.query.strip()
    results: list[InlineQueryResultArticle] = []
    if 2 <= len(text) <= MAX_QUERY_LENGTH:
        try:
            place, fc = await _forecast_for(context, text, user.language_code)
        except (LookupError, WeatherError):
            pass
        else:
            lang = _lang(context)
            description = describe_weather(lang, fc.weather_code, describe(fc.weather_code))
            results.append(
                InlineQueryResultArticle(
                    id=f"{place.latitude:.3f},{place.longitude:.3f}",
                    title=(
                        f"{weather_emoji(fc.weather_code, fc.is_day)} {place.name}: "
                        f"{round(fc.temperature)}{fc.temp_unit}"
                    ),
                    description=description,
                    input_message_content=InputTextMessageContent(
                        build_caption(place.name, fc, INLINE_OUTLOOK_DAYS, lang),
                        parse_mode=ParseMode.HTML,
                    ),
                )
            )
    await inline.answer(results, cache_time=INLINE_CACHE_SECONDS, is_personal=True)


__all__ = [
    "CB_LANG",
    "cmd_air",
    "cmd_alerts",
    "cmd_best",
    "cmd_compare",
    "cmd_lang",
    "on_inline_query",
    "on_lang_callback",
]
