"""Build the HTML caption that accompanies the infographic.

Telegram limits photo captions to 1024 characters, so the text stays compact: a headline
with the main conditions, one line of key metrics, and a short outlook for the next days.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from weather_bot.advice import advice_line
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


def _day_line(day: DayPoint, index: int) -> str:
    name = "Today" if index == 0 else day.date.strftime("%a")
    line = f"{name} {weather_emoji(day.weather_code)} {_deg(day.t_max)}/{_deg(day.t_min)}"
    if day.precipitation_probability_max >= 30:
        line += f" ☔{day.precipitation_probability_max}%"
    return line


def build_caption(place_name: str, fc: Forecast, outlook_days: int = 4) -> str:
    today = fc.today
    emoji = weather_emoji(fc.weather_code, fc.is_day)
    name = escape(place_name)

    lines = [
        f"{emoji} <b>{name}</b>",
        f"🌡 <b>{_deg(fc.temperature)}{fc.temp_unit[-1]}</b> · {describe(fc.weather_code)} · "
        f"feels like {_deg(fc.apparent_temperature)}",
        f"⬆️ {_deg(today.t_max)}  ⬇️ {_deg(today.t_min)}  "
        f"💨 {fc.wind_speed:.0f} {fc.speed_unit} {compass(fc.wind_direction)}  💧 {fc.humidity}%",
        f"☔ {today.precipitation_probability_max}% "
        f"({today.precipitation_sum:.1f} {fc.precip_unit})  "
        f"🔆 UV {today.uv_index_max:.0f} {uv_label(today.uv_index_max)}",
        f"🌅 {today.sunrise.strftime('%H:%M')}  🌇 {today.sunset.strftime('%H:%M')}",
        advice_line(fc),
    ]

    upcoming = fc.daily[1 : 1 + outlook_days]
    if upcoming:
        lines.append("")
        lines.append("📅 <b>Next days</b>")
        lines.extend(_day_line(day, i + 1) for i, day in enumerate(upcoming))

    lines.append("")
    lines.append(f"<i>🕒 Updated {fc.observed_at.strftime('%H:%M')} · {escape(fc.timezone)}</i>")

    caption = "\n".join(lines)
    if len(caption) > CAPTION_LIMIT:
        caption = caption[: CAPTION_LIMIT - 1] + "…"
    return caption


def build_sun_caption(place_name: str, fc: Forecast, now: datetime | None = None) -> str:
    info = sun_info(fc, now)
    name = escape(place_name)
    change = fmt_change(info.change_vs_yesterday)
    daylight = f"☀️ Daylight <b>{fmt_duration(info.daylight)}</b>"
    if change:
        daylight += f" ({change})"
    next_line = f"⏳ {info.next_event.capitalize()} in {fmt_duration(info.time_to_next_event)}"
    ge0, ge1 = info.golden_evening
    lines = [
        f"🌇 <b>{name}</b>",
        f"🌅 Sunrise <b>{info.sunrise.strftime('%H:%M')}</b>  ·  "
        f"🌇 Sunset <b>{info.sunset.strftime('%H:%M')}</b>",
        daylight,
        f"🕛 Solar noon {info.solar_noon.strftime('%H:%M')}  ·  "
        f"✨ Golden hour {ge0.strftime('%H:%M')}–{ge1.strftime('%H:%M')}",
        next_line,
    ]
    upcoming = fc.daily[1:4]
    if upcoming:
        lines.append("")
        lines.append("📅 <b>Next days</b>")
        for d in upcoming:
            rise, sset = d.sunrise.strftime("%H:%M"), d.sunset.strftime("%H:%M")
            lines.append(f"{d.date.strftime('%a')} 🌅 {rise} 🌇 {sset}")
    lines.append("")
    lines.append(f"<i>🕒 Updated {fc.observed_at.strftime('%H:%M')} · {escape(fc.timezone)}</i>")
    caption = "\n".join(lines)
    if len(caption) > CAPTION_LIMIT:
        caption = caption[: CAPTION_LIMIT - 1] + "…"
    return caption
