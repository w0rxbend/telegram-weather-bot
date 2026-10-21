"""Small decision helpers on top of a forecast: comparing places and picking a good hour."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from weather_bot.weather import Forecast, HourPoint

WINDOW_HOURS = 2
MAX_RAIN_PROBABILITY = 30  # percent; wetter hours never qualify
HORIZON_HOURS = 24
COMPARE_MIN_PLACES = 2
COMPARE_MAX_PLACES = 3
COMPARE_SEPARATORS: Final = (",", "|", " vs ", " VS ", " Vs ")


@dataclass(frozen=True)
class Activity:
    key: str
    emoji: str
    ideal_low: float  # °C
    ideal_high: float


ACTIVITIES: dict[str, Activity] = {
    "run": Activity("run", "🏃", 6.0, 16.0),
    "bike": Activity("bike", "🚴", 12.0, 24.0),
    "walk": Activity("walk", "🚶", 10.0, 26.0),
}
ACTIVITY_ALIASES = {
    "running": "run",
    "jog": "run",
    "cycling": "bike",
    "bicycle": "bike",
    "walking": "walk",
    "біг": "run",
    "велосипед": "bike",
    "прогулянка": "walk",
}


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime  # exclusive: the last hour starts WINDOW_HOURS - 1 after ``start``
    temperature: float
    rain: int


def parse_activity(text: str) -> Activity | None:
    word = text.strip().lower()
    return ACTIVITIES.get(ACTIVITY_ALIASES.get(word, word))


def split_places(text: str) -> list[str]:
    """Split "Kyiv, Lviv" / "Kyiv vs Lviv" / "Kyiv | Lviv" into city names."""
    parts = [text]
    for separator in COMPARE_SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [part.strip() for part in parts if part.strip()]


def _celsius(value: float, fc: Forecast) -> float:
    return (value - 32) * 5 / 9 if fc.units == "imperial" else value


def _hour_penalty(hour: HourPoint, fc: Forecast, activity: Activity) -> float | None:
    """0 is perfect; larger is worse; None disqualifies the hour (dark or too wet)."""
    if not hour.is_day or hour.precipitation_probability > MAX_RAIN_PROBABILITY:
        return None
    temp = _celsius(hour.temperature, fc)
    outside = max(activity.ideal_low - temp, temp - activity.ideal_high, 0.0)
    return outside + hour.precipitation_probability / 10


def best_window(fc: Forecast, activity: Activity) -> Window | None:
    hours = fc.next_hours(HORIZON_HOURS)
    best: tuple[float, Window] | None = None
    for i in range(len(hours) - WINDOW_HOURS + 1):
        chunk = hours[i : i + WINDOW_HOURS]
        if chunk[-1].time - chunk[0].time != (WINDOW_HOURS - 1) * (hours[1].time - hours[0].time):
            continue  # a gap in the hourly series
        penalties = [_hour_penalty(h, fc, activity) for h in chunk]
        if any(p is None for p in penalties):
            continue
        score = sum(p for p in penalties if p is not None)
        window = Window(
            start=chunk[0].time,
            end=chunk[-1].time.replace(minute=0) + (hours[1].time - hours[0].time),
            temperature=sum(h.temperature for h in chunk) / WINDOW_HOURS,
            rain=max(h.precipitation_probability for h in chunk),
        )
        if best is None or score < best[0]:
            best = (score, window)
    return best[1] if best else None
