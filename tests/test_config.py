from __future__ import annotations

from pathlib import Path

import pytest

from weather_bot.config import ConfigError, load_settings
from weather_bot.main import build_http_client

GOOD_TOKEN = "123456789:AAH-test_token_value_0123456789abc"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("TG_BOT_TOKEN", "HTTP_TIMEOUT", "USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)  # no stray .env


def test_valid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", GOOD_TOKEN)
    settings = load_settings()
    assert settings.bot_token == GOOD_TOKEN
    assert settings.http_timeout == 15.0
    assert settings.data_dir.is_dir()


def test_missing_token() -> None:
    with pytest.raises(ConfigError, match="not set"):
        load_settings()


def test_malformed_token_is_rejected_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "super-secret-typo")
    with pytest.raises(ConfigError) as info:
        load_settings()
    assert "super-secret-typo" not in str(info.value)


@pytest.mark.parametrize("value", ["abc", "0", "-1", "nan", "inf", "9999"])
def test_bad_timeout(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", GOOD_TOKEN)
    monkeypatch.setenv("HTTP_TIMEOUT", value)
    with pytest.raises(ConfigError, match="HTTP_TIMEOUT"):
        load_settings()


async def test_http_client_does_not_follow_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", GOOD_TOKEN)
    client = build_http_client(load_settings())
    try:
        assert client.follow_redirects is False
        assert client.timeout.read == 15.0
    finally:
        await client.aclose()
