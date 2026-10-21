from __future__ import annotations

import dataclasses

from forecast_helpers import set_hour, with_hours
from weather_bot import alerts, planner
from weather_bot.weather import Forecast


def test_split_places_accepts_commas_pipes_and_vs() -> None:
    assert planner.split_places("Kyiv, Lviv") == ["Kyiv", "Lviv"]
    assert planner.split_places("Kyiv vs Lviv | Odesa") == ["Kyiv", "Lviv", "Odesa"]
    assert planner.split_places(" , ") == []


def test_parse_activity_knows_aliases() -> None:
    assert planner.parse_activity("Run") is planner.ACTIVITIES["run"]
    assert planner.parse_activity("біг") is planner.ACTIVITIES["run"]
    assert planner.parse_activity("swim") is None


def test_best_window_picks_the_driest_comfortable_hours(forecast: Forecast) -> None:
    fc = with_hours(forecast, temp=30.0, rain=0)  # too hot for a run everywhere...
    fc = set_hour(set_hour(fc, 3, temperature=12.0), 4, temperature=12.0)  # ...except 17:00-19:00
    window = planner.best_window(fc, planner.ACTIVITIES["run"])
    assert window is not None
    assert window.start.hour == 17 and window.end.hour == 19
    assert window.temperature == 12.0


def test_no_window_when_it_rains_or_is_dark(forecast: Forecast) -> None:
    assert planner.best_window(with_hours(forecast, rain=80), planner.ACTIVITIES["walk"]) is None
    assert planner.best_window(with_hours(forecast, day=False), planner.ACTIVITIES["walk"]) is None


def test_imperial_temperatures_are_converted(forecast: Forecast) -> None:
    fc = dataclasses.replace(with_hours(forecast, temp=59.0), units="imperial")  # 15 °C
    assert planner.best_window(fc, planner.ACTIVITIES["run"]) is not None


def test_rain_ahead_looks_only_a_few_hours_forward(forecast: Forecast) -> None:
    dry = with_hours(forecast)
    assert alerts.rain_ahead(dry) is None
    soon = set_hour(dry, 2, precipitation_probability=70)
    warning = alerts.rain_ahead(soon)
    assert warning is not None and warning.probability == 70 and warning.time.hour == 16
    late = set_hour(dry, 6, precipitation_probability=90)
    assert alerts.rain_ahead(late) is None


def test_alert_checks_are_throttled_and_cooled_down() -> None:
    data: dict = {}
    assert not alerts.check_due(data, 0)  # not opted in
    alerts.enable(data, chat_id=5)
    assert alerts.check_due(data, 1000)
    assert not alerts.check_due(data, 1000 + alerts.CHECK_INTERVAL_SECONDS - 1)
    assert alerts.check_due(data, 1000 + alerts.CHECK_INTERVAL_SECONDS)
    alerts.mark_sent(data, 5000)
    assert not alerts.check_due(data, 5000 + alerts.COOLDOWN_SECONDS - 1)
    assert alerts.check_due(data, 5000 + alerts.COOLDOWN_SECONDS)
    alerts.disable(data)
    assert alerts.chat_id_for(data) is None
