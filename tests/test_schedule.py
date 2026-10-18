from __future__ import annotations

from datetime import UTC, datetime

import pytest

from weather_bot import schedule as sched


def utc(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def test_parse_times_variants() -> None:
    assert sched.parse_times("7:30 13 18.45, 21h00 7:30") == ["07:30", "13:00", "18:45", "21:00"]
    with pytest.raises(ValueError, match="not a time"):
        sched.parse_times("noon")
    with pytest.raises(ValueError, match="valid time"):
        sched.parse_times("25:00")
    with pytest.raises(ValueError):
        sched.parse_times("   ")


def test_presets_are_sane() -> None:
    assert (
        sched.PRESETS["hourly"].times[0] == "09:00" and sched.PRESETS["hourly"].times[-1] == "21:00"
    )
    assert len(sched.PRESETS["hourly"].times) == 13
    assert sched.PRESETS["every3h"].times == ("06:00", "09:00", "12:00", "15:00", "18:00", "21:00")


def test_set_get_clear_toggle() -> None:
    data: dict = {"awaiting_schedule_times": True}
    s = sched.set_schedule(
        data, times=["19:00", "07:30"], preset="morning_evening", tz="Europe/Kyiv", chat_id=42
    )
    assert s.times == ("07:30", "19:00") and s.chat_id == 42 and s.days == "all"
    assert "awaiting_schedule_times" not in data
    assert sched.toggle_days(data).days == "weekdays"
    # re-setting keeps the days preference
    s = sched.set_schedule(data, times=["08:00"], preset="custom", tz="Europe/Kyiv", chat_id=42)
    assert s.days == "weekdays"
    assert "Custom · 08:00" in s.describe() and "weekdays only" in s.describe()
    assert sched.clear_schedule(data) is True
    assert sched.get_schedule(data) is None
    assert sched.clear_schedule(data) is False


def test_due_times_respects_timezone_grace_and_once_per_day() -> None:
    data: dict = {}
    sched.set_schedule(data, times=["07:30", "19:00"], preset="x", tz="Europe/Kyiv", chat_id=1)
    # 07:30 Kyiv == 04:30 UTC on 2026-10-18 (UTC+3)
    assert sched.due_times(data, utc(2026, 10, 18, 4, 29)) == []
    assert sched.due_times(data, utc(2026, 10, 18, 4, 30)) == ["07:30"]
    assert sched.due_times(data, utc(2026, 10, 18, 4, 39)) == ["07:30"]  # within grace
    assert sched.due_times(data, utc(2026, 10, 18, 4, 41)) == []  # grace over
    sched.mark_sent(data, utc(2026, 10, 18, 4, 31), "07:30")
    assert sched.due_times(data, utc(2026, 10, 18, 4, 35)) == []  # already sent today
    assert sched.due_times(data, utc(2026, 10, 19, 4, 30)) == ["07:30"]  # next day again


def test_weekdays_only() -> None:
    data: dict = {}
    sched.set_schedule(data, times=["10:00"], preset="x", tz="UTC", chat_id=1, days="weekdays")
    assert sched.due_times(data, utc(2026, 10, 17, 10, 0)) == []  # Saturday
    assert sched.due_times(data, utc(2026, 10, 19, 10, 0)) == ["10:00"]  # Monday


def test_next_run() -> None:
    data: dict = {}
    s = sched.set_schedule(data, times=["07:30", "19:00"], preset="x", tz="Europe/Kyiv", chat_id=1)
    nxt = s.next_run(utc(2026, 10, 18, 9, 0))  # 12:00 Kyiv
    assert nxt.strftime("%Y-%m-%d %H:%M") == "2026-10-18 19:00"
    nxt = s.next_run(utc(2026, 10, 18, 17, 0))  # 20:00 Kyiv -> tomorrow morning
    assert nxt.strftime("%Y-%m-%d %H:%M") == "2026-10-19 07:30"
    sched.toggle_days(data)
    s = sched.get_schedule(data)
    nxt = s.next_run(utc(2026, 10, 16, 17, 0))  # Friday evening -> Monday
    assert nxt.strftime("%a %H:%M") == "Mon 07:30"


def test_unknown_timezone_falls_back_to_utc() -> None:
    data: dict = {}
    s = sched.set_schedule(data, times=["10:00"], preset="x", tz="Mars/Olympus", chat_id=1)
    assert str(s.zone) == "UTC"
