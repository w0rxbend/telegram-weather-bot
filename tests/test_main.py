from __future__ import annotations

from pathlib import Path

import pytest
from telegram.ext import AIORateLimiter

from weather_bot import runtime
from weather_bot.config import Settings
from weather_bot.main import MAX_API_RETRIES, build_application
from weather_bot.persistence import SqlitePersistence
from weather_bot.telemetry import UsageTelemetry

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


async def test_shutdown_closes_the_state_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqlitePersistence(tmp_path / "state.sqlite3")
    usage = UsageTelemetry(tmp_path / "usage.sqlite3")
    closed: list[str] = []
    close_store, close_usage = store.close, usage.close
    monkeypatch.setattr(store, "close", lambda: (closed.append("state"), close_store()))
    monkeypatch.setattr(usage, "close", lambda: (closed.append("usage"), close_usage()))
    monkeypatch.setattr(runtime, "_telemetry", usage)
    application = build_application(make_settings(tmp_path), store)
    assert application.post_shutdown is not None
    await application.post_shutdown(application)
    assert closed == ["state", "usage"]
    assert runtime.telemetry() is None
