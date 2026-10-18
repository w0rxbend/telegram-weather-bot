from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from telegram import CallbackQuery, Update

from weather_bot import bot
from weather_bot.privacy import describe_error
from weather_bot.weather import WeatherError, fetch_forecast

SECRET_TEXT = "my secret message 50.4501"


def test_describe_error_has_no_url() -> None:
    request = httpx.Request("GET", "https://x.test/?latitude=50.4501&longitude=30.5234")
    status = httpx.HTTPStatusError("boom", request=request, response=httpx.Response(503))
    assert describe_error(status) == "HTTP 503"
    assert describe_error(httpx.ConnectError("conn", request=request)) == "ConnectError"


async def test_fetch_failure_message_and_cause_are_url_free() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400)))
    with pytest.raises(WeatherError) as info:
        await fetch_forecast(client, 50.4501, 30.5234)
    assert "50.45" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


async def test_on_error_logs_ids_only_and_answers_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    update = Update.de_json(
        {
            "update_id": 7,
            "callback_query": {
                "id": "1",
                "chat_instance": "c",
                "from": {"id": 42, "is_bot": False, "first_name": "Ann"},
                "data": SECRET_TEXT,
            },
        },
        None,
    )
    assert update is not None
    answer = AsyncMock()
    context = SimpleNamespace(error=RuntimeError("kaboom"))
    with caplog.at_level(logging.ERROR), patch.object(CallbackQuery, "answer", answer):
        await bot.on_error(update, context)
    assert SECRET_TEXT not in caplog.text
    assert "update 7 (user 42)" in caplog.text
    answer.assert_awaited_once()
