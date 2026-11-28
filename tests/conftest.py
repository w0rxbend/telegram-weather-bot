from __future__ import annotations

import json
from pathlib import Path

import pytest

from weather_bot.weather import Forecast, parse_forecast

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def payload() -> dict:
    return json.loads((FIXTURES / "forecast.json").read_text())


@pytest.fixture(scope="session")
def forecast(payload: dict) -> Forecast:
    return parse_forecast(payload, "metric")


@pytest.fixture(autouse=True)
def _stub_http_client():
    """Handlers resolve the HTTP client from runtime; tests never hit the network."""
    import httpx

    from weather_bot import runtime

    runtime.set_http(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
    yield
    runtime.set_http(None)


@pytest.fixture(autouse=True)
def _fresh_update_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-user update budget is process-wide; one test must not use up another's."""
    from weather_bot import bot
    from weather_bot.ratelimit import RateLimiter

    monkeypatch.setattr(bot, "_update_limiter", RateLimiter(limit=bot.UPDATES_PER_MINUTE))
