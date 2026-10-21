"""Build the HTML caption that accompanies the infographic.

Telegram limits photo captions to 1024 characters, so the text stays compact: a headline
with the main conditions, one line of key metrics, and a short outlook for the next days.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from weather_bot.advice import advice_line
from weather_bot.i18n import DEFAULT_LANG, Lang, describe_weather, tr, weekday
from weather_bot.render.theme import uv_label
from weather_bot.sun import fmt_change, fmt_duration, sun_info
from weather_bot.weather import DayPoint, Forecast, IconKind, compass, describe, icon_kind

CAPTION_LIMIT = 1024

_EMOJI_DAY: dict[IconKind, str] = {
    "clear": "☀️",
    "mostly-clear": "🌤",
    "partly-cloudy": "⛅",
    "overcast": "☁️",
    "fog": "🌫",
    "drizzle": "🌦",
    "rain": "🌧",
    "heavy-rain": "🌧",
    "snow": "🌨",
    "showers": "🌦",
    "snow-showers": "🌨",
    "thunder": "⛈",
}
_EMOJI_NIGHT: dict[IconKind, str] = {
    **_EMOJI_DAY,
    "clear": "🌙",
    "mostly-clear": "🌙",
    "partly-cloudy": "☁️",
}


def weather_emoji(code: int, is_day: bool = True) -> str:
    kind = icon_kind(code)
    return (_EMOJI_DAY if is_day else _EMOJI_NIGHT).get(kind, "🌡")


def _deg(value: float) -> str:
    return f"{round(value):d}°"


def _day_line(day: DayPoint, index: int, lang: Lang) -> str:
    name = tr(lang, "today") if index == 0 else weekday(lang, day.date)
    line = f"{name} {weather_emoji(day.weather_code)} {_deg(day.t_max)}/{_deg(day.t_min)}"
    if day.precipitation_probability_max >= 30:
        line += f" ☔{day.precipitation_probability_max}%"
    return line


def build_caption(
    place_name: str, fc: Forecast, outlook_days: int = 4, lang: Lang = DEFAULT_LANG
) -> str:
    today = fc.today
    emoji = weather_emoji(fc.weather_code, fc.is_day)
    name = escape(place_name)
    description = describe_weather(lang, fc.weather_code, describe(fc.weather_code))

    lines = [
        f"{emoji} <b>{name}</b>",
        f"🌡 <b>{_deg(fc.temperature)}{fc.temp_unit[-1]}</b> · {description} · "
        f"{tr(lang, 'feels_like')} {_deg(fc.apparent_temperature)}",
        f"⬆️ {_deg(today.t_max)}  ⬇️ {_deg(today.t_min)}  "
        f"💨 {fc.wind_speed:.0f} {fc.speed_unit} {compass(fc.wind_direction)}  💧 {fc.humidity}%",
        f"☔ {today.precipitation_probability_max}% "
        f"({today.precipitation_sum:.1f} {fc.precip_unit})  "
        f"🔆 UV {today.uv_index_max:.0f} {uv_label(today.uv_index_max)}",
        f"🌅 {today.sunrise.strftime('%H:%M')}  🌇 {today.sunset.strftime('%H:%M')}",
        advice_line(fc, lang),
    ]

    upcoming = fc.daily[1 : 1 + outlook_days]
    if upcoming:
        lines.append("")
        lines.append(f"📅 <b>{tr(lang, 'next_days')}</b>")
        lines.extend(_day_line(day, i + 1, lang) for i, day in enumerate(upcoming))

    lines.append("")
    lines.append(_footer(fc, lang))

    caption = "\n".join(lines)
    if len(caption) > CAPTION_LIMIT:
        caption = caption[: CAPTION_LIMIT - 1] + "…"
    return caption


def _footer(fc: Forecast, lang: Lang) -> str:
    stamp = fc.observed_at.strftime("%H:%M")
    return f"<i>🕒 {tr(lang, 'updated')} {stamp} · {escape(fc.timezone)}</i>"


def build_sun_caption(
    place_name: str, fc: Forecast, now: datetime | None = None, lang: Lang = DEFAULT_LANG
) -> str:
    info = sun_info(fc, now)
    name = escape(place_name)
    change = fmt_change(info.change_vs_yesterday)
    daylight = f"☀️ {tr(lang, 'daylight')} <b>{fmt_duration(info.daylight)}</b>"
    if change:
        daylight += f" ({change})"
    next_line = f"⏳ {info.next_event.capitalize()} in {fmt_duration(info.time_to_next_event)}"
    ge0, ge1 = info.golden_evening
    lines = [
        f"🌇 <b>{name}</b>",
        f"🌅 {tr(lang, 'sunrise')} <b>{info.sunrise.strftime('%H:%M')}</b>  ·  "
        f"🌇 {tr(lang, 'sunset')} <b>{info.sunset.strftime('%H:%M')}</b>",
        daylight,
        f"🕛 {tr(lang, 'solar_noon')} {info.solar_noon.strftime('%H:%M')}  ·  "
        f"✨ {tr(lang, 'golden_hour')} {ge0.strftime('%H:%M')}–{ge1.strftime('%H:%M')}",
        next_line,
    ]
    upcoming = fc.daily[1:4]
    if upcoming:
        lines.append("")
        lines.append(f"📅 <b>{tr(lang, 'next_days')}</b>")
        for d in upcoming:
            rise, sset = d.sunrise.strftime("%H:%M"), d.sunset.strftime("%H:%M")
            lines.append(f"{weekday(lang, d.date)} 🌅 {rise} 🌇 {sset}")
    lines.append("")
    lines.append(_footer(fc, lang))
    caption = "\n".join(lines)
    if len(caption) > CAPTION_LIMIT:
        caption = caption[: CAPTION_LIMIT - 1] + "…"
    return caption
