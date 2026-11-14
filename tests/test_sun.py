from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from weather_bot.caption import build_caption, build_sun_caption
from weather_bot.render.card import render_image
from weather_bot.render.sun_card import render_sun_image
from weather_bot.sun import NO_TIME, fmt_change, fmt_duration, sun_clock, sun_info
from weather_bot.weather import Forecast, parse_forecast


def test_daytime(forecast: Forecast) -> None:
    info = sun_info(forecast, datetime(2026, 10, 17, 12, 35))
    assert info.is_day
    assert info.sunrise.strftime("%H:%M") == "07:12"
    assert info.sunset.strftime("%H:%M") == "17:59"
    assert fmt_duration(info.daylight) == "10h 47m"
    assert info.solar_noon.strftime("%H:%M") == "12:35"
    assert abs(info.progress - 0.5) < 0.01
    assert info.next_event == "sunset"
    assert fmt_duration(info.time_to_next_event) == "5h 24m"
    assert info.change_vs_yesterday is None  # fixture has no past day
    assert info.golden_evening[0].strftime("%H:%M") == "16:59"


def test_evening_and_early_morning(forecast: Forecast) -> None:
    evening = sun_info(forecast, datetime(2026, 10, 17, 21, 0))
    assert not evening.is_day and evening.next_event == "sunrise"
    assert evening.progress == 1.0
    assert 0 < evening.night_progress < 0.5
    assert evening.time_to_next_event == forecast.tomorrow.sunrise - datetime(2026, 10, 17, 21, 0)

    morning = sun_info(forecast, datetime(2026, 10, 17, 6, 0))
    assert not morning.is_day and morning.next_event == "sunrise"
    assert morning.night_progress > 0.9
    assert fmt_duration(morning.time_to_next_event) == "1h 12m"


def test_yesterday_is_split_off_and_used_for_change(payload: dict) -> None:
    data = {**payload, "daily": {k: list(v) for k, v in payload["daily"].items()}}
    daily = data["daily"]
    daily["time"].insert(0, "2026-10-16")
    daily["weather_code"].insert(0, 1)
    daily["temperature_2m_max"].insert(0, 15.0)
    daily["temperature_2m_min"].insert(0, 8.0)
    daily["sunrise"].insert(0, "2026-10-16T07:10")
    daily["sunset"].insert(0, "2026-10-16T18:01")
    daily["uv_index_max"].insert(0, 3.0)
    daily["precipitation_probability_max"].insert(0, 0)
    daily["precipitation_sum"].insert(0, 0.0)
    fc = parse_forecast(data, "metric")
    assert fc.today.date.day == 17
    assert fc.yesterday is not None and fc.yesterday.date.day == 16
    assert len(fc.daily) == 7
    info = sun_info(fc, datetime(2026, 10, 17, 12, 0))
    assert info.change_vs_yesterday == timedelta(minutes=-4)
    assert fmt_change(info.change_vs_yesterday) == "−4 min vs yesterday"
    assert fmt_change(timedelta(0)) == "same as yesterday"
    assert fmt_change(None) == ""


def test_polar_edge_does_not_crash(forecast: Forecast) -> None:
    flat = replace(forecast.today, sunrise=forecast.today.date, sunset=forecast.today.date)
    fc = replace(forecast, daily=[flat, *forecast.daily[1:]])
    info = sun_info(fc, datetime(2026, 10, 17, 12, 0))
    assert fmt_duration(info.daylight) == "0m"


def _polar(forecast: Forecast, kind: str) -> Forecast:
    """Days shaped as Open-Meteo reports them inside the polar circles (checked live)."""
    length = timedelta(days=1) if kind == "day" else timedelta(0)
    days = [replace(d, sunrise=d.date, sunset=d.date + length) for d in forecast.daily]
    return replace(forecast, daily=days, yesterday=None)


def test_polar_night_and_day_are_recognised(forecast: Forecast) -> None:
    noon = datetime(2026, 10, 17, 12, 0)
    assert sun_info(forecast, noon).polar is None

    night = sun_info(_polar(forecast, "night"), noon)
    assert night.polar == "night" and not night.is_day
    assert night.progress == 0.0  # no part of the day arc is drawn as travelled
    assert fmt_duration(night.daylight) == "0m"

    day = sun_info(_polar(forecast, "day"), noon)
    assert day.polar == "day" and day.is_day
    assert day.daylight == timedelta(hours=24)


def test_sun_clock_has_no_times_on_a_polar_day(forecast: Forecast) -> None:
    assert sun_clock(forecast.today) == ("07:12", "17:59")
    assert sun_clock(_polar(forecast, "night").today) == (NO_TIME, NO_TIME)
    assert sun_clock(_polar(forecast, "day").today) == (NO_TIME, NO_TIME)


@pytest.mark.parametrize("kind", ["night", "day"])
def test_captions_do_not_invent_sun_times_in_polar_regions(forecast: Forecast, kind: str) -> None:
    fc = _polar(forecast, kind)
    noon = datetime(2026, 10, 17, 12, 0)
    card, sun = build_caption("Longyearbyen", fc), build_sun_caption("Longyearbyen", fc, now=noon)
    for caption in (card, sun):
        assert f"Polar {kind}" in caption
        assert "00:00" not in caption
    assert "Golden hour" not in sun and " in " not in sun.split("\n")[1]
    assert "Полярн" in build_caption("Longyearbyen", fc, lang="uk")


@pytest.mark.parametrize("kind", ["night", "day"])
def test_cards_render_in_polar_regions(forecast: Forecast, kind: str) -> None:
    fc = _polar(forecast, kind)
    noon = datetime(2026, 10, 17, 12, 0)
    assert render_image(fc, "Longyearbyen", now=noon).size[0] > 0
    assert render_sun_image(fc, "Longyearbyen", now=noon).size[0] > 0
