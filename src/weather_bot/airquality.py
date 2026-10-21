"""Air quality from Open-Meteo's free air-quality API (European AQI and particulates)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from weather_bot.httpcap import get_capped
from weather_bot.i18n import Lang, tr
from weather_bot.privacy import describe_error
from weather_bot.weather import WeatherError

AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
CURRENT_FIELDS = ("european_aqi", "pm2_5", "pm10")

# (exclusive upper bound, label key, emoji) - the European Air Quality Index bands
_BANDS: tuple[tuple[float, str, str], ...] = (
    (20, "aqi_good", "🟢"),
    (40, "aqi_fair", "🟡"),
    (60, "aqi_moderate", "🟠"),
    (80, "aqi_poor", "🔴"),
    (100, "aqi_very_poor", "🟣"),
)
_EXTREME = ("aqi_extreme", "🟤")


@dataclass(frozen=True)
class AirQuality:
    aqi: int
    pm2_5: float
    pm10: float

    def label(self, lang: Lang) -> str:
        key, emoji = next(((k, e) for limit, k, e in _BANDS if self.aqi < limit), _EXTREME)
        return f"{emoji} {tr(lang, key)}"


def parse_air_quality(payload: dict[str, Any]) -> AirQuality:
    try:
        current = payload["current"]
        return AirQuality(
            aqi=round(float(current["european_aqi"])),
            pm2_5=float(current["pm2_5"]),
            pm10=float(current["pm10"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError("Air quality data is missing for this place") from exc


async def fetch_air_quality(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> AirQuality:
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "current": ",".join(CURRENT_FIELDS),
    }
    try:
        response = await get_capped(client, AIR_QUALITY_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise WeatherError(f"Air quality request failed: {describe_error(exc)}") from None
    except ValueError as exc:
        raise WeatherError("Air quality API returned invalid JSON") from exc
    return parse_air_quality(payload)
