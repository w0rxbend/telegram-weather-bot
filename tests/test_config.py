from __future__ import annotations

from pathlib import Path

import pytest

from weather_bot.config import load_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "1:token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # keep python-dotenv away from a developer's real .env


def test_defaults() -> None:
    settings = load_settings()
    assert settings.http_timeout == 15 and settings.forecast_cache_ttl == 3600


@pytest.mark.parametrize("name", ["HTTP_TIMEOUT", "FORECAST_CACHE_TTL"])
@pytest.mark.parametrize("value", ["abc", "0", "-5", "nan", "inf"])
def test_invalid_numbers_are_rejected_at_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=name):
        load_settings()


def test_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", " ")
    with pytest.raises(RuntimeError, match="TG_BOT_TOKEN"):
        load_settings()
