from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from telegram import Bot, Message, Update, User
from telegram.error import NetworkError
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler

from weather_bot import bot
from weather_bot.weather import WeatherError, fetch_forecast

CHAT = {"id": 1, "type": "private"}
USER = {"id": 1, "is_bot": False, "first_name": "Ann"}


def _message(**extra: object) -> dict:
    return {"message_id": 1, "date": 1700000000, "chat": CHAT, "from": USER, **extra}


@pytest.fixture(autouse=True)
def _offline_bot_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """CommandHandler asks the bot for its username; avoid the getMe network call."""
    me = User(id=1, is_bot=True, first_name="Weather", username="weather_test_bot")
    monkeypatch.setattr(Bot, "bot", property(lambda self: me))


def _update(kind: str, **extra: object) -> Update:
    return Update.de_json({"update_id": 1, kind: _message(**extra)}, Bot("1:test"))


def _matching(update: Update) -> list[object]:
    app = ApplicationBuilder().token("1:test").build()
    bot.register_handlers(app)
    return [
        h.callback.__name__
        for h in app.handlers[0]
        if isinstance(h, CommandHandler | MessageHandler) and h.check_update(update)
    ]


def test_command_is_routed() -> None:
    update = _update(
        "message", text="/weather", entities=[{"type": "bot_command", "offset": 0, "length": 8}]
    )
    assert _matching(update) == ["cmd_weather"]


def test_edited_command_is_ignored() -> None:
    update = _update(
        "edited_message",
        text="/weather",
        entities=[{"type": "bot_command", "offset": 0, "length": 8}],
    )
    assert _matching(update) == []


def test_live_location_updates_are_ignored() -> None:
    edited = _update("edited_message", location={"latitude": 1.0, "longitude": 2.0})
    assert _matching(edited) == []
    fresh = _update("message", location={"latitude": 1.0, "longitude": 2.0})
    assert _matching(fresh) == ["on_location"]


def test_edited_text_is_ignored() -> None:
    assert _matching(_update("edited_message", text="Kyiv")) == []


async def test_error_handler_logs_update_id_not_content(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Message, "reply_text", AsyncMock())
    update = _update("message", text="secret-city", location={"latitude": 12.345, "longitude": 6.7})
    context = SimpleNamespace(error=RuntimeError("boom"))
    with caplog.at_level(logging.ERROR):
        await bot.on_error(update, context)  # type: ignore[arg-type]
    assert "secret-city" not in caplog.text
    assert "12.345" not in caplog.text
    assert "update 1" in caplog.text


async def test_weather_error_message_does_not_contain_coordinates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WeatherError) as info:
            await fetch_forecast(client, 50.4501, 30.5234)
    assert "50.45" not in str(info.value)
    assert "HTTP 400" in str(info.value)


async def test_error_handler_survives_failing_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Message, "reply_text", AsyncMock(side_effect=NetworkError("down")))
    update = _update("message", text="x")
    await bot.on_error(update, SimpleNamespace(error=RuntimeError("boom")))  # type: ignore[arg-type]
