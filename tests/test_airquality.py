from __future__ import annotations

import httpx
import pytest

from weather_bot.airquality import AirQuality, fetch_air_quality, parse_air_quality
from weather_bot.weather import WeatherError


@pytest.mark.parametrize(
    ("aqi", "label"),
    [
        (0, "🟢 Good"),
        (20, "🟡 Fair"),
        (45, "🟠 Moderate"),
        (79, "🔴 Poor"),
        (99, "🟣 Very poor"),
        (150, "🟤 Extremely poor"),
    ],
)
def test_aqi_bands(aqi: int, label: str) -> None:
    assert AirQuality(aqi, 1.0, 2.0).label("en") == label


def test_label_is_localised() -> None:
    assert AirQuality(10, 1.0, 2.0).label("uk") == "🟢 Добра"


def test_parse_rounds_aqi_and_rejects_missing_data() -> None:
    payload = {"current": {"european_aqi": 33.6, "pm2_5": 8.2, "pm10": 12.0}}
    assert parse_air_quality(payload) == AirQuality(34, 8.2, 12.0)
    with pytest.raises(WeatherError):
        parse_air_quality({"current": {"european_aqi": None, "pm2_5": 1, "pm10": 1}})
    with pytest.raises(WeatherError):
        parse_air_quality({})


async def test_fetch_sends_coordinates_and_parses() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"current": {"european_aqi": 18, "pm2_5": 4.0, "pm10": 7.0}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        air = await fetch_air_quality(client, 50.45, 30.52)
    assert air.aqi == 18
    assert seen[0].url.params["latitude"] == "50.4500"


async def test_fetch_failure_does_not_leak_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WeatherError) as info:
            await fetch_air_quality(client, 50.45, 30.52)
    assert "50.45" not in str(info.value)
