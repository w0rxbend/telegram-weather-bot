"""Sunrise / sunset arithmetic for the sun card and the sun tile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from weather_bot.weather import DayPoint, Forecast

GOLDEN_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class SunInfo:
    sunrise: datetime
    sunset: datetime
    solar_noon: datetime
    daylight: timedelta
    change_vs_yesterday: timedelta | None
    is_day: bool
    progress: float  # 0..1 from sunrise to sunset while the sun is up
    night_progress: float  # 0..1 from sunset to the next sunrise while it is down
    next_event: str  # "sunset" or "sunrise"
    time_to_next_event: timedelta

    @property
    def golden_morning(self) -> tuple[datetime, datetime]:
        return self.sunrise, self.sunrise + GOLDEN_HOUR

    @property
    def golden_evening(self) -> tuple[datetime, datetime]:
        return self.sunset - GOLDEN_HOUR, self.sunset


def daylight_of(day: DayPoint) -> timedelta:
    return max(day.sunset - day.sunrise, timedelta(0))


def _fraction(start: datetime, end: datetime, now: datetime) -> float:
    span = (end - start).total_seconds()
    if span <= 0:
        return 0.0
    return min(1.0, max(0.0, (now - start).total_seconds() / span))


def sun_info(fc: Forecast, now: datetime | None = None) -> SunInfo:
    now = now or fc.local_now()
    today = fc.today
    sunrise, sunset = today.sunrise, today.sunset
    daylight = daylight_of(today)
    change = daylight - daylight_of(fc.yesterday) if fc.yesterday else None
    is_day = sunrise <= now < sunset

    if is_day:
        progress = _fraction(sunrise, sunset, now)
        night_progress = 0.0
        next_event, until = "sunset", sunset - now
    elif now < sunrise:
        prev_sunset = fc.yesterday.sunset if fc.yesterday else sunset - timedelta(days=1)
        progress = 0.0
        night_progress = _fraction(prev_sunset, sunrise, now)
        next_event, until = "sunrise", sunrise - now
    else:
        next_sunrise = fc.tomorrow.sunrise if fc.tomorrow else sunrise + timedelta(days=1)
        progress = 1.0
        night_progress = _fraction(sunset, next_sunrise, now)
        next_event, until = "sunrise", next_sunrise - now

    return SunInfo(
        sunrise=sunrise,
        sunset=sunset,
        solar_noon=sunrise + daylight / 2,
        daylight=daylight,
        change_vs_yesterday=change,
        is_day=is_day,
        progress=progress,
        night_progress=night_progress,
        next_event=next_event,
        time_to_next_event=max(until, timedelta(0)),
    )


def fmt_duration(delta: timedelta) -> str:
    total = round(delta.total_seconds() / 60)
    hours, minutes = divmod(abs(total), 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def fmt_change(delta: timedelta | None) -> str:
    if delta is None:
        return ""
    total = round(delta.total_seconds() / 60)
    if total == 0:
        return "same as yesterday"
    sign = "+" if total > 0 else "−"
    return f"{sign}{abs(total)} min vs yesterday"
