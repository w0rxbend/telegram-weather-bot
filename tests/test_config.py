from __future__ import annotations

import stat
from pathlib import Path

import pytest

from weather_bot.config import ConfigError, load_settings

VALID_TOKEN = "123456789:" + "A" * 35


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # keep python-dotenv from finding a developer's .env
    for name in ("TG_BOT_TOKEN", "DATA_DIR", "HTTP_TIMEOUT", "USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_missing_token_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="TG_BOT_TOKEN is not set"):
        load_settings()


def test_malformed_token_is_rejected_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "super-secret-but-wrong")
    with pytest.raises(ConfigError) as info:
        load_settings()
    assert "super-secret" not in str(info.value)


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "nan", "inf"])
def test_invalid_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("HTTP_TIMEOUT", raw)
    with pytest.raises(ConfigError, match="HTTP_TIMEOUT"):
        load_settings()


def test_valid_settings_create_a_private_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", VALID_TOKEN)
    settings = load_settings()
    assert settings.http_timeout == 15.0
    assert stat.S_IMODE(settings.data_dir.stat().st_mode) == 0o700
