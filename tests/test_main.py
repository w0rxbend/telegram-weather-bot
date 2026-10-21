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


async def test_shutdown_closes_state_and_telemetry_stores(tmp_path: Path) -> None:
    from weather_bot import runtime
    from weather_bot.telemetry import UsageTelemetry

    settings = Settings(
        bot_token=TOKEN, data_dir=tmp_path, http_timeout=5.0, user_agent="weather-bot-test"
    )
    store = SqlitePersistence(tmp_path / "state.sqlite3")
    telemetry = UsageTelemetry(tmp_path / "telemetry.sqlite3")
    runtime.set_telemetry(telemetry)
    closed: list[str] = []
    store.close = lambda: closed.append("state")  # type: ignore[method-assign]
    telemetry.close = lambda: closed.append("telemetry")  # type: ignore[method-assign]
    try:
        application = build_application(settings, store)
        assert application.post_shutdown is not None
        await application.post_shutdown(application)
    finally:
        runtime.set_telemetry(None)
    assert closed == ["state", "telemetry"]
