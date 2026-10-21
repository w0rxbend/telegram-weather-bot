from __future__ import annotations

from pathlib import Path

import pytest
from telegram.ext import AIORateLimiter

from weather_bot.config import Settings
from weather_bot.main import MAX_API_RETRIES, build_application
from weather_bot.persistence import SqlitePersistence

TOKEN = "123456:" + "A" * 35


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token=TOKEN, data_dir=tmp_path, http_timeout=5.0, user_agent="weather-bot-test"
    )


def test_application_retries_bot_api_flood_control(tmp_path: Path) -> None:
    application = build_application(
        make_settings(tmp_path), SqlitePersistence(tmp_path / "state.sqlite3")
    )
    limiter = application.bot.rate_limiter
    assert isinstance(limiter, AIORateLimiter)
    assert limiter._max_retries == MAX_API_RETRIES


async def test_shutdown_closes_the_state_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqlitePersistence(tmp_path / "state.sqlite3")
    closed: list[bool] = []
    monkeypatch.setattr(store, "close", lambda: closed.append(True))
    application = build_application(make_settings(tmp_path), store)
    assert application.post_shutdown is not None
    await application.post_shutdown(application)
    assert closed == [True]
