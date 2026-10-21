from __future__ import annotations

from pathlib import Path

from telegram.ext import AIORateLimiter

from weather_bot.config import Settings
from weather_bot.main import MAX_API_RETRIES, build_application
from weather_bot.persistence import SqlitePersistence

TOKEN = "123456:" + "A" * 35


def test_application_retries_bot_api_flood_control(tmp_path: Path) -> None:
    settings = Settings(
        bot_token=TOKEN, data_dir=tmp_path, http_timeout=5.0, user_agent="weather-bot-test"
    )
    application = build_application(settings, SqlitePersistence(tmp_path / "state.sqlite3"))
    limiter = application.bot.rate_limiter
    assert isinstance(limiter, AIORateLimiter)
    assert limiter._max_retries == MAX_API_RETRIES
