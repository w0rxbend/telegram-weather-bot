from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from weather_bot import bot, runtime, telemetry
from weather_bot.telemetry import UsageTelemetry, city_label


@pytest.fixture
def usage(tmp_path: Path):
    recorder = UsageTelemetry(tmp_path / "telemetry.sqlite3")
    runtime.set_telemetry(recorder)
    yield recorder
    runtime.set_telemetry(None)
    runtime.set_admin_ids(frozenset())
    recorder.close()


def test_city_label_drops_private_alias() -> None:
    assert city_label("home · Kyiv, Ukraine") == "Kyiv, Ukraine"
    assert city_label("Lviv, Ukraine") == "Lviv, Ukraine"


def test_file_is_owner_only(usage: UsageTelemetry, tmp_path: Path) -> None:
    mode = (tmp_path / "telemetry.sqlite3").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


async def test_counts_events_users_and_cities(usage: UsageTelemetry) -> None:
    await usage.record_event(1, "cmd_weather", "ann", "en")
    await usage.record_event(1, "cmd_weather")  # later calls must not erase the username
    await usage.record_event(2, "cmd_sun", None, "uk")
    with telemetry.acting_as(1):
        await usage.record_card("home · Kyiv, Ukraine", "weather")
        await usage.record_card("Kyiv, Ukraine", "weather")
    with telemetry.acting_as(2):
        await usage.record_card("Lviv, Ukraine", "sun")
    report = await usage.report()
    assert (report.users, report.cards) == (2, 3)
    assert report.top_cities[0] == telemetry.Ranked("Kyiv, Ukraine", 2)
    assert report.top_users[0].label == "@ann (1)"
    assert report.top_users[0].count == 4  # 2 commands + 2 cards


async def test_card_without_actor_is_ignored(usage: UsageTelemetry) -> None:
    await usage.record_card("Kyiv, Ukraine", "weather")
    assert (await usage.report()).cards == 0


def _stats_update(user_id: int) -> SimpleNamespace:
    message = MagicMock()
    message.reply_text = AsyncMock()
    return SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=user_id))


async def test_stats_is_admin_only(usage: UsageTelemetry) -> None:
    runtime.set_admin_ids(frozenset({7}))
    await usage.record_event(1, "cmd_weather", "<b>x</b>")
    stranger = _stats_update(1)
    await bot.cmd_stats(stranger, SimpleNamespace())  # type: ignore[arg-type]
    stranger.effective_message.reply_text.assert_not_called()

    admin = _stats_update(7)
    await bot.cmd_stats(admin, SimpleNamespace())  # type: ignore[arg-type]
    text = admin.effective_message.reply_text.call_args.args[0]
    assert "1 users" in text
    assert "<b>x</b>" not in text  # usernames are HTML-escaped
