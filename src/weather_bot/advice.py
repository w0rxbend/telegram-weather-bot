"""One-line practical tips derived from the forecast: what to wear and what to bring."""

from __future__ import annotations

from weather_bot.i18n import DEFAULT_LANG, Lang, tr
from weather_bot.weather import Forecast

RAIN_PROBABILITY = 50  # percent; at or above this, suggest an umbrella
UV_SPF = 6  # WHO "high" band starts here
WIND_KMH = 30.0
MPH_PER_KMH = 0.621371

_CLOTHING_BANDS: tuple[tuple[float, str], ...] = (  # (upper bound in °C, string key)
    (-5.0, "coat_winter"),
    (5.0, "coat_warm"),
    (14.0, "coat_light"),
    (22.0, "sleeves"),
)
_WARM_TIP = "tshirt"
_EMOJI = {
    "coat_winter": "🧥",
    "coat_warm": "🧥",
    "coat_light": "🧥",
    "sleeves": "👕",
    "tshirt": "🩳",
    "umbrella": "☂️",
    "spf": "🧴",
    "windy": "💨",
}


def _to_celsius(value: float, fc: Forecast) -> float:
    return (value - 32) * 5 / 9 if fc.units == "imperial" else value


def _wind_kmh(fc: Forecast) -> float:
    return fc.wind_gusts / MPH_PER_KMH if fc.units == "imperial" else fc.wind_gusts


def advice_line(fc: Forecast, lang: Lang = DEFAULT_LANG) -> str:
    """Tips joined by " · ", e.g. "🧥 Light jacket · ☂️ Umbrella"; judged on how it feels now."""
    feels = _to_celsius(fc.apparent_temperature, fc)
    keys = [next((key for limit, key in _CLOTHING_BANDS if feels < limit), _WARM_TIP)]
    if fc.today.precipitation_probability_max >= RAIN_PROBABILITY:
        keys.append("umbrella")
    if fc.today.uv_index_max >= UV_SPF:
        keys.append("spf")
    if _wind_kmh(fc) >= WIND_KMH:
        keys.append("windy")
    return " · ".join(f"{_EMOJI[key]} {tr(lang, key)}" for key in keys)
