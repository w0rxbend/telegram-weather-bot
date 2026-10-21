"""Builders for forecasts with controlled hourly data."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from weather_bot.weather import Forecast, HourPoint


def with_hours(fc: Forecast, *, temp: float = 15.0, rain: int = 0, day: bool = True) -> Forecast:
    start = fc.observed_at.replace(minute=0, second=0, microsecond=0)
    hours = [HourPoint(start + timedelta(hours=i), temp, rain, 0, day) for i in range(30)]
    return dataclasses.replace(fc, hourly=hours)


def set_hour(fc: Forecast, offset: int, **changes: object) -> Forecast:
    hours = list(fc.hourly)
    hours[offset] = dataclasses.replace(hours[offset], **changes)
    return dataclasses.replace(fc, hourly=hours)
