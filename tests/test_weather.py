from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest

from weather_bot import weather
from weather_bot.weather import (
    Forecast,
    WeatherError,
    build_params,
    compass,
    describe,
    fetch_forecast,
    icon_kind,
    parse_forecast,
)


def test_parse_current(forecast: Forecast) -> None:
    assert forecast.temperature == 15.6
    assert forecast.apparent_temperature == 13.9
    assert forecast.humidity == 72
    assert forecast.is_day is True
    assert forecast.weather_code == 80
    assert forecast.timezone == "Europe/Kyiv"
    assert forecast.utc_offset == timedelta(hours=3)
    assert forecast.observed_at == datetime(2026, 10, 17, 14, 15)
    assert forecast.temp_unit == "°C"
    assert forecast.speed_unit == "km/h"


def test_parse_series(forecast: Forecast) -> None:
    assert len(forecast.hourly) == 24 * 7
    assert len(forecast.daily) == 7
    today = forecast.today
    assert today.t_max == 17.4
    assert today.t_min == 9.1
    assert today.sunrise.hour == 7
    assert today.precipitation_probability_max == 70


def test_next_hours_starts_at_current_hour(forecast: Forecast) -> None:
    hours = forecast.next_hours(24)
    assert len(hours) == 24
    assert hours[0].time == datetime(2026, 10, 17, 14, 0)
    assert hours[-1].time == datetime(2026, 10, 18, 13, 0)


def test_imperial_units(payload: dict) -> None:
    fc = parse_forecast(payload, "imperial")
    assert fc.temp_unit == "°F"
    assert fc.speed_unit == "mph"
    assert fc.precip_unit == "in"
    params = build_params(1, 2, "imperial")
    assert params["temperature_unit"] == "fahrenheit"
    assert "temperature_unit" not in build_params(1, 2, "metric")


def test_parse_rejects_garbage() -> None:
    with pytest.raises(WeatherError):
        parse_forecast({"current": {}}, "metric")


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (0, "clear"),
        (1, "mostly-clear"),
        (2, "partly-cloudy"),
        (3, "overcast"),
        (45, "fog"),
        (48, "fog"),
        (53, "drizzle"),
        (61, "rain"),
        (65, "heavy-rain"),
        (71, "snow"),
        (77, "snow"),
        (81, "showers"),
        (86, "snow-showers"),
        (95, "thunder"),
        (99, "thunder"),
        (1234, "overcast"),
    ],
)
def test_icon_kind(code: int, kind: str) -> None:
    assert icon_kind(code) == kind


def test_describe() -> None:
    assert describe(0) == "Clear sky"
    assert describe(95) == "Thunderstorm"
    assert describe(-1) == "Unknown"


@pytest.mark.parametrize(
    ("deg", "name"), [(0, "N"), (22, "N"), (45, "NE"), (180, "S"), (359, "N"), (300, "NW")]
)
def test_compass(deg: float, name: str) -> None:
    assert compass(deg) == name


async def test_fetch_forecast_retries_on_429(
    payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(weather, "RETRY_DELAYS", (0, 0))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        assert request.url.params["latitude"] == "50.4500"
        return httpx.Response(200, content=json.dumps(payload))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fc = await fetch_forecast(client, 50.45, 30.52)
    assert calls == 2
    assert fc.temperature == 15.6


async def test_fetch_forecast_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather, "RETRY_DELAYS", (0, 0))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WeatherError):
            await fetch_forecast(client, 50.45, 30.52)


async def test_fetch_forecast_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": True, "reason": "Latitude must be in range"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WeatherError, match="Latitude"):
            await fetch_forecast(client, 999, 0)
