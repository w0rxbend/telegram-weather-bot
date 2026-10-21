from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Chat, Message, Update, User
from telegram.error import TelegramError

from weather_bot import bot

SECRET_TEXT = "my-secret-home-address"


def make_real_update() -> Update:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=5, type="private"),
        from_user=User(id=5, first_name="Ann", is_bot=False),
        text=SECRET_TEXT,
    )
    return Update(update_id=77, message=message)


async def test_on_error_logs_ids_but_not_message_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = SimpleNamespace(error=RuntimeError("boom"))
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(Message, "reply_text", AsyncMock(return_value=None)) as reply,
    ):
        await bot.on_error(make_real_update(), context)  # type: ignore[arg-type]
    assert "77" in caplog.text
    assert SECRET_TEXT not in caplog.text
    assert "Ann" not in caplog.text
    reply.assert_awaited_once()


async def test_on_error_survives_failing_notice(caplog: pytest.LogCaptureFixture) -> None:
    context = SimpleNamespace(error=RuntimeError("boom"))
    failing = AsyncMock(side_effect=TelegramError("blocked"))
    with caplog.at_level(logging.DEBUG), patch.object(Message, "reply_text", failing):
        await bot.on_error(make_real_update(), context)  # type: ignore[arg-type]
    failing.assert_awaited_once()


async def test_on_error_accepts_non_update_objects() -> None:
    await bot.on_error(None, SimpleNamespace(error=RuntimeError("boom")))  # type: ignore[arg-type]
