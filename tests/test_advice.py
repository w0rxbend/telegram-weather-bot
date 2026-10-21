from __future__ import annotations

import dataclasses

from weather_bot.advice import advice_line
from weather_bot.caption import CAPTION_LIMIT, build_caption
from weather_bot.weather import Forecast


def _with(
    fc: Forecast, *, feels: float, rain: int = 0, uv: float = 0, gusts: float = 0
) -> Forecast:
    today = dataclasses.replace(fc.today, precipitation_probability_max=rain, uv_index_max=uv)
    return dataclasses.replace(
        fc,
        apparent_temperature=feels,
        wind_gusts=gusts,
        daily=[today, *fc.daily[1:]],
    )


def test_clothing_follows_how_it_feels(forecast: Forecast) -> None:
    assert advice_line(_with(forecast, feels=-10)) == "🧥 Winter coat"
    assert advice_line(_with(forecast, feels=0)) == "🧥 Warm jacket"
    assert advice_line(_with(forecast, feels=10)) == "🧥 Light jacket"
    assert advice_line(_with(forecast, feels=18)) == "👕 Long sleeves"
    assert advice_line(_with(forecast, feels=30)) == "🩳 T-shirt weather"


def test_extra_tips_are_added_at_their_thresholds(forecast: Forecast) -> None:
    line = advice_line(_with(forecast, feels=18, rain=50, uv=6, gusts=30))
    assert line == "👕 Long sleeves · ☂️ Umbrella · 🧴 SPF · 💨 Windy"
    assert advice_line(_with(forecast, feels=18, rain=49, uv=5.9, gusts=29)) == "👕 Long sleeves"


def test_imperial_values_are_converted(forecast: Forecast) -> None:
    fc = dataclasses.replace(_with(forecast, feels=32, gusts=20), units="imperial")  # 0 °C, 32 km/h
    assert advice_line(fc) == "🧥 Warm jacket · 💨 Windy"


def test_caption_has_advice_and_stays_within_limit(forecast: Forecast) -> None:
    worst = _with(forecast, feels=18, rain=90, uv=9, gusts=60)
    caption = build_caption("A" * 60, worst)
    assert "☂️ Umbrella" in caption
    assert len(caption) <= CAPTION_LIMIT
    assert "Updated" in caption  # the footer must not be truncated away
