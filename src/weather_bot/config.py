"""Runtime configuration read from environment variables (and an optional .env file)."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
DEFAULT_HTTP_TIMEOUT = 15.0
MAX_HTTP_TIMEOUT = 120.0


class ConfigError(RuntimeError):
    """The environment does not describe a runnable bot."""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    data_dir: Path
    http_timeout: float
    user_agent: str

    @property
    def heartbeat_file(self) -> Path:
        return self.data_dir / "heartbeat"

    @property
    def persistence_file(self) -> Path:
        return self.data_dir / "bot_state.pickle"


def _parse_timeout(raw: str | None) -> float:
    if raw is None or not raw.strip():
        return DEFAULT_HTTP_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"HTTP_TIMEOUT must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(value) or not 0 < value <= MAX_HTTP_TIMEOUT:
        raise ConfigError(f"HTTP_TIMEOUT must be in (0, {MAX_HTTP_TIMEOUT:.0f}] seconds")
    return value


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("TG_BOT_TOKEN is not set. Put it in the environment or in a .env file.")
    if not TOKEN_PATTERN.match(token):
        # Deliberately not echoing the value: it may be a real secret with a typo.
        raise ConfigError("TG_BOT_TOKEN does not look like a BotFather token (<digits>:<secret>).")

    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        data_dir=data_dir,
        http_timeout=_parse_timeout(os.getenv("HTTP_TIMEOUT")),
        user_agent=os.getenv(
            "USER_AGENT",
            "telegram-weather-bot/1.0 (+https://github.com/w0rxbend/telegram-weather-bot)",
        ),
    )
