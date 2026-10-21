"""One-line practical tips derived from the forecast: what to wear and what to bring."""

from __future__ import annotations

from weather_bot.weather import Forecast

RAIN_PROBABILITY = 50  # percent; at or above this, suggest an umbrella
UV_SPF = 6  # WHO "high" band starts here
WIND_KMH = 30.0
MPH_PER_KMH = 0.621371

_CLOTHING_BANDS: tuple[tuple[float, str], ...] = (  # (upper bound in °C, tip)
    (-5.0, "🧥 Winter coat"),
    (5.0, "🧥 Warm jacket"),
    (14.0, "🧥 Light jacket"),
    (22.0, "👕 Long sleeves"),
)
_WARM_TIP = "🩳 T-shirt weather"


def _to_celsius(value: float, fc: Forecast) -> float:
    return (value - 32) * 5 / 9 if fc.units == "imperial" else value


def _wind_kmh(fc: Forecast) -> float:
    return fc.wind_gusts / MPH_PER_KMH if fc.units == "imperial" else fc.wind_gusts


def advice_line(fc: Forecast) -> str:
    """Tips joined by " · ", e.g. "🧥 Light jacket · ☂️ Umbrella"; judged on how it feels now."""
    feels = _to_celsius(fc.apparent_temperature, fc)
    tips = [next((tip for limit, tip in _CLOTHING_BANDS if feels < limit), _WARM_TIP)]
    if fc.today.precipitation_probability_max >= RAIN_PROBABILITY:
        tips.append("☂️ Umbrella")
    if fc.today.uv_index_max >= UV_SPF:
        tips.append("🧴 SPF")
    if _wind_kmh(fc) >= WIND_KMH:
        tips.append("💨 Windy")
    return " · ".join(tips)
