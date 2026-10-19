from __future__ import annotations

from pathlib import Path

import pytest

from weather_bot.config import load_settings

TOKEN = "123456:" + "A" * 35


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no stray .env
    for name in ("TG_BOT_TOKEN", "HTTP_TIMEOUT", "DATA_DIR"):
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
