"""Opt-in rain alerts: spot rain in the next hours and say so at most once per cooldown.

State lives in ``user_data["rain_alerts"]``::

    {"chat_id": int, "last_sent": float | None, "checked": float | None}
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from weather_bot.weather import Forecast

KEY_ALERTS = "rain_alerts"
RAIN_PROBABILITY = 60  # percent in a single hour
LOOKAHEAD_HOURS = 3
COOLDOWN_SECONDS = 6 * 3600
CHECK_INTERVAL_SECONDS = 15 * 60

UserData = MutableMapping[str, Any]


@dataclass(frozen=True)
class RainWarning:
    time: datetime
    probability: int


def rain_ahead(fc: Forecast) -> RainWarning | None:
    """The first hour within the lookahead whose rain probability reaches the threshold."""
    for hour in fc.next_hours(LOOKAHEAD_HOURS + 1):
        if hour.precipitation_probability >= RAIN_PROBABILITY:
            return RainWarning(hour.time, hour.precipitation_probability)
    return None


def enable(user_data: UserData, chat_id: int) -> None:
    user_data[KEY_ALERTS] = {"chat_id": chat_id, "last_sent": None, "checked": None}


def disable(user_data: UserData) -> None:
    user_data.pop(KEY_ALERTS, None)


def chat_id_for(user_data: UserData) -> int | None:
    state = user_data.get(KEY_ALERTS)
    return state.get("chat_id") if isinstance(state, dict) else None


def check_due(user_data: UserData, now: float) -> bool:
    """True when this user's forecast should be inspected now; marks the check."""
    state = user_data.get(KEY_ALERTS)
    if not isinstance(state, dict):
        return False
    last_sent, checked = state.get("last_sent"), state.get("checked")
    if last_sent is not None and now - last_sent < COOLDOWN_SECONDS:
        return False
    if checked is not None and now - checked < CHECK_INTERVAL_SECONDS:
        return False
    state["checked"] = now  # not persisted on its own: only a throttle against refetch storms
    return True


def mark_sent(user_data: UserData, now: float) -> None:
    state = user_data.get(KEY_ALERTS)
    if isinstance(state, dict):
        state["last_sent"] = now
