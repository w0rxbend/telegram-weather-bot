from __future__ import annotations

from dataclasses import replace

from weather_bot.caption import CAPTION_LIMIT, build_caption, weather_emoji
from weather_bot.weather import Forecast, parse_forecast


def test_caption_contains_main_weather(forecast: Forecast) -> None:
    caption = build_caption("Kyiv, Ukraine", forecast)
    assert caption.startswith("🌦 <b>Kyiv, Ukraine</b>")
    assert "🌡 <b>16°C</b> · Light showers · feels like 14°" in caption
    assert "⬆️ 17°  ⬇️ 9°" in caption
    assert "💨 14 km/h NW" in caption
    assert "💧 72%" in caption
    assert "☔ 70% (4.1 mm)" in caption
    assert "🔆 UV 3 Moderate" in caption
    assert "🌅 07:12  🌇 17:59" in caption
    assert "📅 <b>Next days</b>" in caption
    assert "Sun ⛅ 19°/8°" in caption
    assert "Tue 🌧 14°/8° ☔85%" in caption
    assert "🕒 Updated 14:15 · Europe/Kyiv" in caption
    assert len(caption) <= CAPTION_LIMIT


def test_caption_imperial(payload: dict) -> None:
    fc = parse_forecast(payload, "imperial")
    caption = build_caption("New York", fc)
    assert "°F</b>" in caption
    assert "mph" in caption


def test_caption_escapes_html(forecast: Forecast) -> None:
    caption = build_caption("<Evil> & Co", forecast)
    assert "&lt;Evil&gt; &amp; Co" in caption


def test_caption_is_truncated_when_too_long(forecast: Forecast) -> None:
    caption = build_caption("X" * 2000, forecast)
    assert len(caption) == CAPTION_LIMIT
    assert caption.endswith("…")


def test_weather_emoji_day_night() -> None:
    assert weather_emoji(0, True) == "☀️"
    assert weather_emoji(0, False) == "🌙"
    assert weather_emoji(95) == "⛈"
    assert weather_emoji(71) == "🌨"


def test_caption_without_outlook(forecast: Forecast) -> None:
    fc = replace(forecast, daily=forecast.daily[:1])
    caption = build_caption("Somewhere", fc)
    assert "Next days" not in caption


def test_sun_caption(forecast: Forecast) -> None:
    from datetime import datetime

    from weather_bot.caption import build_sun_caption

    caption = build_sun_caption("Kyiv, Ukraine", forecast, datetime(2026, 10, 17, 14, 15))
    assert caption.startswith("🌇 <b>Kyiv, Ukraine</b>")
    assert "🌅 Sunrise <b>07:12</b>" in caption and "🌇 Sunset <b>17:59</b>" in caption
    assert "☀️ Daylight <b>10h 47m</b>" in caption
    assert "✨ Golden hour 16:59–17:59" in caption
    assert "⏳ Sunset in 3h 44m" in caption
    assert "Sun 🌅 07:13 🌇 17:57" in caption
    assert len(caption) <= CAPTION_LIMIT
