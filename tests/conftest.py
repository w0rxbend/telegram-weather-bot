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
