from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.error import BadRequest, Forbidden, RetryAfter

from weather_bot import locations as store
from weather_bot import schedule as sched
from weather_bot import scheduler
from weather_bot.geocode import Place
from weather_bot.weather import Forecast

KYIV = Place("Kyiv, Ukraine", 50.45, 30.52)


def make_app(user_data: dict[int, dict]) -> SimpleNamespace:
    app = SimpleNamespace()
    app.user_data = user_data
    app.bot = SimpleNamespace(send_photo=AsyncMock())
    app.mark_data_for_update_persistence = lambda **kw: app.__dict__.setdefault(
        "marked", []
    ).append(kw)
    app.update_persistence = AsyncMock()
    return app


async def test_tick_sends_due_card_once(forecast: Forecast) -> None:
    data: dict = {"units": "metric"}
    store.add_location(data, KYIV)
    sched.set_schedule(data, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=777)
    app = make_app({1: data})
    now = datetime(2026, 10, 18, 4, 31, tzinfo=UTC)  # 07:31 Kyiv
    with patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))):
        assert await scheduler.tick(app, now) == 1
        assert await scheduler.tick(app, now) == 0  # not twice
    call = app.bot.send_photo.await_args.kwargs
    assert call["chat_id"] == 777 and call["photo"] == b"png"
    assert "Kyiv, Ukraine" in call["caption"]
    assert app.marked == [{"user_ids": [1]}, {"user_ids": [1]}]
    assert app.update_persistence.await_count == 2  # marks saved before sending, results after


async def test_tick_persists_sent_marks_before_sending(forecast: Forecast) -> None:
    data: dict = {}
    store.add_location(data, KYIV)
    sched.set_schedule(data, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=777)
    app = make_app({1: data})
    order: list[str] = []
    app.update_persistence = AsyncMock(side_effect=lambda: order.append("persist"))
    app.bot.send_photo = AsyncMock(side_effect=lambda **_: order.append("send"))
    now = datetime(2026, 10, 18, 4, 31, tzinfo=UTC)
    with patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))):
        await scheduler.tick(app, now)
    # a crash between the send and the final save must not resend the card after a restart
    assert order == ["persist", "send", "persist"]


async def test_tick_skips_users_without_schedule_or_not_due(forecast: Forecast) -> None:
    data: dict = {}
    store.add_location(data, KYIV)
    sched.set_schedule(data, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=1)
    app = make_app({1: data, 2: {"units": "metric"}})
    assert await scheduler.tick(app, datetime(2026, 10, 18, 12, 0, tzinfo=UTC)) == 0
    app.bot.send_photo.assert_not_awaited()


async def test_blocked_user_schedule_is_removed(forecast: Forecast) -> None:
    data: dict = {}
    store.add_location(data, KYIV)
    sched.set_schedule(data, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=1)
    app = make_app({1: data})
    app.bot.send_photo = AsyncMock(side_effect=Forbidden("blocked"))
    with patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))):
        await scheduler.tick(app, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    assert sched.get_schedule(data) is None


async def test_schedule_without_location_is_cleared() -> None:
    data: dict = {}
    sched.set_schedule(data, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=1)
    app = make_app({1: data})
    await scheduler.tick(app, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    assert sched.get_schedule(data) is None
    app.bot.send_photo.assert_not_awaited()


async def test_one_failing_user_does_not_block_others(forecast: Forecast) -> None:
    first: dict = {}
    store.add_location(first, KYIV)
    sched.set_schedule(first, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=1)
    second: dict = {}
    store.add_location(second, KYIV)
    sched.set_schedule(second, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=2)
    app = make_app({1: first, 2: second})
    app.bot.send_photo = AsyncMock(side_effect=[RuntimeError("boom"), None])
    with patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))):
        assert await scheduler.tick(app, datetime(2026, 10, 18, 4, 30, tzinfo=UTC)) == 1
    assert app.bot.send_photo.await_count == 2


def _scheduled_app(chat_id: int = 1) -> tuple[SimpleNamespace, dict]:
    data: dict = {}
    store.add_location(data, KYIV)
    sched.set_schedule(data, times=["07:30"], preset="morning", tz="Europe/Kyiv", chat_id=chat_id)
    return make_app({1: data}), data


async def test_flood_control_is_waited_out_once(forecast: Forecast) -> None:
    app, _ = _scheduled_app()
    app.bot.send_photo = AsyncMock(side_effect=[RetryAfter(2), None])
    sleep = AsyncMock()
    with (
        patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))),
        patch("weather_bot.scheduler.asyncio.sleep", sleep),
    ):
        await scheduler.tick(app, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    assert app.bot.send_photo.await_count == 2
    sleep.assert_awaited_once_with(2.0)


async def test_long_flood_control_wait_is_not_slept(forecast: Forecast) -> None:
    app, _ = _scheduled_app()
    app.bot.send_photo = AsyncMock(side_effect=RetryAfter(3600))
    sleep = AsyncMock()
    with (
        patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))),
        patch("weather_bot.scheduler.asyncio.sleep", sleep),
    ):
        await scheduler.tick(app, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    sleep.assert_not_awaited()
    assert app.bot.send_photo.await_count == 1


async def test_vanished_chat_removes_schedule(forecast: Forecast) -> None:
    app, data = _scheduled_app()
    app.bot.send_photo = AsyncMock(side_effect=BadRequest("Chat not found"))
    with patch("weather_bot.bot._build_card", AsyncMock(return_value=(b"png", forecast))):
        await scheduler.tick(app, datetime(2026, 10, 18, 4, 30, tzinfo=UTC))
    assert sched.get_schedule(data) is None
