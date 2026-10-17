from __future__ import annotations

import io
from dataclasses import replace
from datetime import datetime

import pytest
from PIL import Image

from weather_bot.render import render_card
from weather_bot.render.card import HEIGHT, WIDTH, render_image
from weather_bot.render.icons import icon
from weather_bot.render.theme import temp_colour, theme_for, uv_label
from weather_bot.weather import Forecast, parse_forecast

ALL_KINDS = [
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


def test_render_card_is_png_of_expected_size(forecast: Forecast) -> None:
    png = render_card(forecast, "Kyiv, Ukraine", now=datetime(2026, 10, 17, 14, 15))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    image = Image.open(io.BytesIO(png))
    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "RGB"
    assert len(png) < 1_500_000


def test_render_imperial(payload: dict) -> None:
    fc = parse_forecast(payload, "imperial")
    image = render_image(fc, "New York", now=fc.observed_at)
    assert image.size == (WIDTH, HEIGHT)


@pytest.mark.parametrize("code", [0, 3, 45, 65, 75, 95])
@pytest.mark.parametrize("is_day", [True, False])
def test_render_every_theme(forecast: Forecast, code: int, is_day: bool) -> None:
    fc = replace(forecast, weather_code=code, is_day=is_day)
    image = render_image(fc, "Anywhere", now=fc.observed_at)
    assert image.size == (WIDTH, HEIGHT)


def test_long_place_name_is_truncated(forecast: Forecast) -> None:
    name = "Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch, Wales, United Kingdom"
    image = render_image(forecast, name, now=forecast.observed_at)
    assert image.size == (WIDTH, HEIGHT)


def test_flat_temperatures_do_not_crash(forecast: Forecast) -> None:
    flat_hours = [replace(h, temperature=10.0) for h in forecast.hourly]
    flat_days = [replace(d, t_max=10.0, t_min=10.0) for d in forecast.daily]
    fc = replace(forecast, hourly=flat_hours, daily=flat_days)
    assert render_image(fc, "Flatland", now=fc.observed_at).size == (WIDTH, HEIGHT)


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("is_day", [True, False])
def test_icons_render_with_content(kind: str, is_day: bool) -> None:
    im = icon(kind, is_day, 64)
    assert im.size == (64, 64)
    assert im.mode == "RGBA"
    assert im.getbbox() is not None, "icon is fully transparent"


def test_theme_lookup_has_fallback() -> None:
    assert theme_for("overcast", True) is theme_for("nonsense", True)  # type: ignore[arg-type]
    assert theme_for("clear", True) != theme_for("clear", False)


def test_temp_colour_ramp() -> None:
    cold = temp_colour(-30)
    hot = temp_colour(45)
    mild = temp_colour(18)
    assert cold[2] > cold[0]  # blue-ish
    assert hot[0] > hot[2]  # red-ish
    assert all(
        abs(a - b) <= 1
        for a, b in zip(temp_colour(64.4, imperial=True), temp_colour(18), strict=True)
    )
    assert all(0 <= channel <= 255 for channel in mild)


def test_uv_label() -> None:
    assert uv_label(0) == "Low"
    assert uv_label(5.9) == "Moderate"
    assert uv_label(11) == "Extreme"
