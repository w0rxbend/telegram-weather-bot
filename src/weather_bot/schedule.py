"""Per-user notification schedules: presets, custom times and "what is due now" logic.

State lives in ``user_data["schedule"]``::

    {"preset": "three", "times": ["07:30", "13:00", "19:00"], "days": "all" | "weekdays",
     "tz": "Europe/Kyiv", "chat_id": 123, "last": {"date": "2026-10-18", "sent": ["07:30"]}}

Times are local wall-clock times in the schedule's time zone (the default location's zone).
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KEY_SCHEDULE = "schedule"
KEY_AWAITING_TIMES = "awaiting_schedule_times"

MAX_TIMES = 24
GRACE = timedelta(minutes=10)  # a slot still fires if the bot was busy/down for up to this long

UserData = MutableMapping[str, Any]


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    times: tuple[str, ...]


PRESETS: dict[str, Preset] = {
    p.key: p
    for p in (
        Preset("morning", "🌅 Every morning · 07:30", ("07:30",)),
        Preset("morning_evening", "🌅🌇 Morning & evening · 07:30, 19:00", ("07:30", "19:00")),
        Preset("three", "3️⃣ Three times a day · 07:30, 13:00, 19:00", ("07:30", "13:00", "19:00")),
        Preset("hourly", "🕘 Every hour · 09:00–21:00", tuple(f"{h:02d}:00" for h in range(9, 22))),
        Preset(
            "every3h",
            "⏱ Every 3 hours · 06:00–21:00",
            tuple(f"{h:02d}:00" for h in range(6, 22, 3)),
        ),
    )
}


@dataclass(frozen=True)
class Schedule:
    preset: str
    times: tuple[str, ...]
    days: str  # "all" | "weekdays"
    tz: str
    chat_id: int

    @property
    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def describe(self) -> str:
        preset = PRESETS.get(self.preset)
        if preset:
            head = preset.label
        elif len(self.times) <= 6:
            head = "✏️ Custom · " + ", ".join(self.times)
        else:
            head = f"✏️ Custom · {len(self.times)} times ({self.times[0]}–{self.times[-1]})"
        days = "weekdays only" if self.days == "weekdays" else "every day"
        return f"{head} · {days} · {self.tz}"

    def next_run(self, now_utc: datetime) -> datetime | None:
        """Next local datetime a card will be sent, or None when nothing is scheduled."""
        if not self.times:
            return None
        local = now_utc.astimezone(self.zone)
        for day_offset in range(0, 8):
            day = (local + timedelta(days=day_offset)).date()
            if self.days == "weekdays" and day.weekday() >= 5:
                continue
            for t in self.times:
                hh, mm = (int(x) for x in t.split(":"))
                candidate = datetime.combine(day, datetime.min.time(), tzinfo=self.zone).replace(
                    hour=hh, minute=mm
                )
                if candidate > local:
                    return candidate
        return None


# --- parsing -----------------------------------------------------------------------------

_TIME_RE = re.compile(r"^(\d{1,2})(?:[:h.](\d{2}))?$")


def parse_times(text: str) -> list[str]:
    """Parse "7:30 12 18.45 21h00" into sorted, unique "HH:MM" strings.

    Raises ValueError with a user-facing message on bad input.
    """
    tokens = [t for t in re.split(r"[\s,;]+", text.strip()) if t]
    if not tokens:
        raise ValueError("Send the times you want, e.g. 7:30 13:00 19:00")
    times: set[str] = set()
    for token in tokens:
        m = _TIME_RE.match(token.lower())
        if not m:
            raise ValueError(f"“{token}” is not a time. Use HH:MM, e.g. 7:30 13:00 19:00")
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"“{token}” is not a valid time of day")
        times.add(f"{hh:02d}:{mm:02d}")
    if len(times) > MAX_TIMES:
        raise ValueError(f"That is too many times; the limit is {MAX_TIMES} per day")
    return sorted(times)


# --- state ---------------------------------------------------------------------------------


def get_schedule(user_data: UserData) -> Schedule | None:
    raw = user_data.get(KEY_SCHEDULE)
    if not raw or not raw.get("times"):
        return None
    return Schedule(
        preset=raw.get("preset", "custom"),
        times=tuple(raw["times"]),
        days=raw.get("days", "all"),
        tz=raw.get("tz", "UTC"),
        chat_id=int(raw["chat_id"]),
    )


def set_schedule(
    user_data: UserData,
    *,
    times: list[str] | tuple[str, ...],
    preset: str,
    tz: str,
    chat_id: int,
    days: str | None = None,
) -> Schedule:
    previous = user_data.get(KEY_SCHEDULE) or {}
    user_data[KEY_SCHEDULE] = {
        "preset": preset,
        "times": sorted(set(times)),
        "days": days or previous.get("days", "all"),
        "tz": tz,
        "chat_id": chat_id,
        "last": {"date": "", "sent": []},
    }
    user_data.pop(KEY_AWAITING_TIMES, None)
    return get_schedule(user_data)  # type: ignore[return-value]


def clear_schedule(user_data: UserData) -> bool:
    user_data.pop(KEY_AWAITING_TIMES, None)
    return user_data.pop(KEY_SCHEDULE, None) is not None


def toggle_days(user_data: UserData) -> Schedule | None:
    raw = user_data.get(KEY_SCHEDULE)
    if not raw:
        return None
    raw["days"] = "all" if raw.get("days", "all") == "weekdays" else "weekdays"
    return get_schedule(user_data)


def update_timezone(user_data: UserData, tz: str) -> None:
    raw = user_data.get(KEY_SCHEDULE)
    if raw and tz and raw.get("tz") != tz:
        raw["tz"] = tz


# --- firing --------------------------------------------------------------------------------


def due_times(user_data: UserData, now_utc: datetime) -> list[str]:
    """Slots that should fire now and have not fired today yet."""
    sched = get_schedule(user_data)
    if sched is None:
        return []
    local = now_utc.astimezone(sched.zone)
    if sched.days == "weekdays" and local.weekday() >= 5:
        return []
    today = local.date().isoformat()
    last = user_data[KEY_SCHEDULE].get("last") or {}
    sent = set(last.get("sent", [])) if last.get("date") == today else set()
    now_minutes = local.hour * 60 + local.minute
    due = []
    for t in sched.times:
        if t in sent:
            continue
        hh, mm = (int(x) for x in t.split(":"))
        start = hh * 60 + mm
        if start <= now_minutes <= start + GRACE.total_seconds() / 60:
            due.append(t)
    return due


def mark_sent(user_data: UserData, now_utc: datetime, slot: str) -> None:
    sched = get_schedule(user_data)
    if sched is None:
        return
    today = now_utc.astimezone(sched.zone).date().isoformat()
    raw = user_data[KEY_SCHEDULE]
    last = raw.get("last") or {}
    if last.get("date") != today:
        last = {"date": today, "sent": []}
    if slot not in last["sent"]:
        last["sent"].append(slot)
    raw["last"] = last
