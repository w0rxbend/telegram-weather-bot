from __future__ import annotations

from pathlib import Path

import pytest

from weather_bot.config import load_settings

TOKEN = "123456:" + "A" * 35


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no stray .env
    for name in ("TG_BOT_TOKEN", "HTTP_TIMEOUT", "DATA_DIR", "FORECAST_CACHE_TTL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_loads_valid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", f" {TOKEN} ")
    settings = load_settings()
    assert settings.bot_token == TOKEN
    assert settings.http_timeout == 15.0
    assert settings.data_dir.is_dir()


def test_missing_token_fails() -> None:
    with pytest.raises(RuntimeError, match="TG_BOT_TOKEN is not set"):
        load_settings()


def test_malformed_token_fails_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "not-a-real-token-value")
    with pytest.raises(RuntimeError) as info:
        load_settings()
    assert "not-a-real-token-value" not in str(info.value)


@pytest.mark.parametrize("value", ["abc", "0", "-1", "inf", "nan"])
def test_bad_timeout_fails(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("HTTP_TIMEOUT", value)
    with pytest.raises(RuntimeError, match="HTTP_TIMEOUT"):
        load_settings()


def test_admin_ids_parsed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "123456789:" + "a" * 30)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_USER_IDS", "1, 22,")
    assert load_settings().admin_ids == frozenset({1, 22})
    monkeypatch.setenv("ADMIN_USER_IDS", "me")
    with pytest.raises(RuntimeError, match="ADMIN_USER_IDS"):
        load_settings()


def test_forecast_cache_ttl_is_read_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-51: a bad value fails at startup with the variable's name, not at import."""
    monkeypatch.setenv("TG_BOT_TOKEN", TOKEN)
    assert load_settings().forecast_cache_ttl == 3600.0
    monkeypatch.setenv("FORECAST_CACHE_TTL", "600")
    assert load_settings().forecast_cache_ttl == 600.0
    for bad in ("soon", "0", "nan"):
        monkeypatch.setenv("FORECAST_CACHE_TTL", bad)
        with pytest.raises(RuntimeError, match="FORECAST_CACHE_TTL"):
            load_settings()
