"""Open-Meteo client and the data model used by the renderer.

Open-Meteo (https://open-meteo.com) is free for non-commercial use and needs no API key.
All timestamps are returned in the location's local time (``timezone=auto``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from weather_bot.httpio import read_json_capped
from weather_bot.privacy import describe_error

Units = Literal["metric", "imperial"]

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_FIELDS = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "is_day",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]
HOURLY_FIELDS = ["temperature_2m", "precipitation_probability", "weather_code", "is_day"]
DAILY_FIELDS = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "sunrise",
    "sunset",
    "uv_index_max",
    "precipitation_probability_max",
    "precipitation_sum",
]


class WeatherError(Exception):
    """Raised when the forecast cannot be fetched or parsed."""


@dataclass(frozen=True)
class HourPoint:
    time: datetime
    temperature: float
    precipitation_probability: int
    weather_code: int
    is_day: bool


@dataclass(frozen=True)
class DayPoint:
    date: datetime
    weather_code: int
    t_max: float
    t_min: float
    sunrise: datetime
    sunset: datetime
    uv_index_max: float
    precipitation_probability_max: int
    precipitation_sum: float


@dataclass(frozen=True)
class Forecast:
    latitude: float
    longitude: float
    timezone: str
    utc_offset: timedelta
    units: Units
    observed_at: datetime
    temperature: float
    apparent_temperature: float
    humidity: int
    is_day: bool
    precipitation: float
    weather_code: int
    cloud_cover: int
    pressure: float
    wind_speed: float
    wind_direction: int
    wind_gusts: float
    hourly: list[HourPoint] = field(default_factory=list)
    daily: list[DayPoint] = field(default_factory=list)  # starts with today
    yesterday: DayPoint | None = None

    @property
    def today(self) -> DayPoint:
        return self.daily[0]

    @property
    def tomorrow(self) -> DayPoint | None:
        return self.daily[1] if len(self.daily) > 1 else None

    @property
    def temp_unit(self) -> str:
        return "°F" if self.units == "imperial" else "°C"

    @property
    def speed_unit(self) -> str:
        return "mph" if self.units == "imperial" else "km/h"

    @property
    def precip_unit(self) -> str:
        return "in" if self.units == "imperial" else "mm"

    def local_now(self) -> datetime:
        return datetime.now(timezone(self.utc_offset)).replace(tzinfo=None)

    def next_hours(self, count: int = 24) -> list[HourPoint]:
        """Hourly points starting from the current hour."""
        start = self.observed_at.replace(minute=0, second=0, microsecond=0)
        points = [p for p in self.hourly if p.time >= start]
        return points[:count]


# --- WMO weather interpretation codes -------------------------------------------------------

WMO_DESCRIPTIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm, hail",
    99: "Thunderstorm, heavy hail",
}

IconKind = Literal[
    "clear",
    "mostly-clear",
    "partly-cloudy",
    "overcast",
    "fog",
    "drizzle",
    "rain",
    "heavy-rain",
    "snow",
    "showers",
    "snow-showers",
    "thunder",
]


def describe(code: int) -> str:
    return WMO_DESCRIPTIONS.get(code, "Unknown")


def icon_kind(code: int) -> IconKind:
    """Collapse the WMO code into the set of icons the renderer knows how to draw."""
    if code == 0:
        return "clear"
    if code == 1:
        return "mostly-clear"
    if code == 2:
        return "partly-cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if code in (61, 63, 66):
        return "rain"
    if code in (65, 67):
        return "heavy-rain"
    if 71 <= code <= 77:
        return "snow"
    if 80 <= code <= 82:
        return "showers"
    if code in (85, 86):
        return "snow-showers"
    if code in (95, 96, 99):
        return "thunder"
    return "overcast"


def compass(degrees: float) -> str:
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return names[int((degrees + 22.5) // 45) % 8]


# --- Fetching ------------------------------------------------------------------------------


def build_params(latitude: float, longitude: float, units: Units) -> dict[str, Any]:
    params: dict[str, Any] = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "current": ",".join(CURRENT_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "daily": ",".join(DAILY_FIELDS),
        "timezone": "auto",
        "forecast_days": 7,
        "past_days": 1,
    }
    if units == "imperial":
        params.update(
            temperature_unit="fahrenheit",
            wind_speed_unit="mph",
            precipitation_unit="inch",
        )
    return params


RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_DELAYS = (1.0, 2.5)


async def fetch_forecast(
    client: httpx.AsyncClient, latitude: float, longitude: float, units: Units = "metric"
) -> Forecast:
    """Fetch and parse the forecast, retrying briefly on rate limits and server errors."""
    params = build_params(latitude, longitude, units)
    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            async with client.stream("GET", FORECAST_URL, params=params) as response:
                if response.status_code in RETRY_STATUSES and attempt < len(RETRY_DELAYS):
                    retry = True
                else:
                    retry = False
                    response.raise_for_status()
                    payload = await read_json_capped(response)
            if retry:
                await asyncio.sleep(RETRY_DELAYS[attempt])
                continue
            break
        except httpx.TransportError as exc:
            last_error = exc
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(RETRY_DELAYS[attempt])
                continue
            raise WeatherError(
                f"Open-Meteo request failed: {describe_error(exc)}"
            ) from None  # the cause embeds the request URL (PII)
        except httpx.HTTPError as exc:
            raise WeatherError(
                f"Open-Meteo request failed: {describe_error(exc)}"
            ) from None  # the cause embeds the request URL (PII)
        except ValueError as exc:
            raise WeatherError("Open-Meteo returned invalid JSON") from exc
    else:  # pragma: no cover - loop always breaks or raises
        raise WeatherError(f"Open-Meteo request failed: {last_error}")

    if "error" in payload and payload.get("error"):
        raise WeatherError(payload.get("reason", "Open-Meteo returned an error"))

    return parse_forecast(payload, units)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def parse_forecast(payload: dict[str, Any], units: Units) -> Forecast:
    try:
        cur = payload["current"]
        hourly = payload["hourly"]
        daily = payload["daily"]

        hourly_points = [
            HourPoint(
                time=_ts(t),
                temperature=float(temp),
                precipitation_probability=int(prob or 0),
                weather_code=int(code),
                is_day=bool(day),
            )
            for t, temp, prob, code, day in zip(
                hourly["time"],
                hourly["temperature_2m"],
                hourly["precipitation_probability"],
                hourly["weather_code"],
                hourly["is_day"],
                strict=True,
            )
            if temp is not None and code is not None
        ]

        daily_points = [
            DayPoint(
                date=_ts(d),
                weather_code=int(code),
                t_max=float(tmax),
                t_min=float(tmin),
                sunrise=_ts(rise or f"{d}T00:00"),
                sunset=_ts(sset or f"{d}T00:00"),
                uv_index_max=float(uv or 0),
                precipitation_probability_max=int(prob or 0),
                precipitation_sum=float(psum or 0),
            )
            for d, code, tmax, tmin, rise, sset, uv, prob, psum in zip(
                daily["time"],
                daily["weather_code"],
                daily["temperature_2m_max"],
                daily["temperature_2m_min"],
                daily["sunrise"],
                daily["sunset"],
                daily["uv_index_max"],
                daily["precipitation_probability_max"],
                daily["precipitation_sum"],
                strict=True,
            )
            if code is not None and tmax is not None and tmin is not None
        ]

        if not daily_points or not hourly_points:
            raise WeatherError("Open-Meteo returned an empty forecast")

        observed_at = _ts(cur["time"])
        past = [d for d in daily_points if d.date.date() < observed_at.date()]
        daily_points = [d for d in daily_points if d.date.date() >= observed_at.date()]
        if not daily_points:
            raise WeatherError("Open-Meteo forecast does not cover today")

        return Forecast(
            latitude=float(payload["latitude"]),
            longitude=float(payload["longitude"]),
            timezone=str(payload.get("timezone", "UTC")),
            utc_offset=timedelta(seconds=int(payload.get("utc_offset_seconds", 0))),
            units=units,
            observed_at=observed_at,
            temperature=float(cur["temperature_2m"]),
            apparent_temperature=float(cur["apparent_temperature"]),
            humidity=int(cur["relative_humidity_2m"]),
            is_day=bool(cur["is_day"]),
            precipitation=float(cur.get("precipitation") or 0),
            weather_code=int(cur["weather_code"]),
            cloud_cover=int(cur.get("cloud_cover") or 0),
            pressure=float(cur.get("pressure_msl") or 0),
            wind_speed=float(cur["wind_speed_10m"]),
            wind_direction=int(cur.get("wind_direction_10m") or 0),
            wind_gusts=float(cur.get("wind_gusts_10m") or 0),
            hourly=hourly_points,
            daily=daily_points,
            yesterday=past[-1] if past else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError(f"Unexpected Open-Meteo payload: {exc!r}") from exc
