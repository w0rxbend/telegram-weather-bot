"""Build the HTML caption that accompanies the infographic.

Telegram limits photo captions to 1024 characters, so the text stays compact: a headline
with the main conditions, one line of key metrics, and a short outlook for the next days.
"""

from __future__ import annotations

from html import escape

from weather_bot.render.theme import uv_label
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
