"""Runtime configuration read from environment variables (and an optional .env file)."""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Bot API tokens look like "<numeric bot id>:<35 url-safe chars>"; reject obvious typos early
# without being so strict that a future token format would be refused.
_TOKEN_RE = re.compile(r"^\d{3,}:[A-Za-z0-9_-]{20,}$")
DEFAULT_HTTP_TIMEOUT = "15"
PRIVATE_DIR_MODE = 0o700


class ConfigError(RuntimeError):
    """Raised at startup when the environment configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    data_dir: Path
    http_timeout: float
    user_agent: str

    @property
    def persistence_file(self) -> Path:
        return self.data_dir / "bot_state.pickle"


def _parse_timeout(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"HTTP_TIMEOUT must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"HTTP_TIMEOUT must be a positive number of seconds, got {raw!r}")
    return value


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("TG_BOT_TOKEN is not set. Put it in the environment or in a .env file.")
    if not _TOKEN_RE.match(token):
        # Never echo the value: it may be a real, mistyped secret.
        raise ConfigError("TG_BOT_TOKEN does not look like a Telegram bot token (id:secret).")

    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser()
    data_dir.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    # The state file is a pickle: only this process (user) may read or write it.
    try:
        data_dir.chmod(PRIVATE_DIR_MODE)
    except PermissionError:  # e.g. a bind mount owned by another user: keep running
        log.warning("Could not restrict permissions on %s; check its ownership", data_dir)

    return Settings(
        bot_token=token,
        data_dir=data_dir,
        http_timeout=_parse_timeout(os.getenv("HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT)),
        user_agent=os.getenv(
            "USER_AGENT",
            "telegram-weather-bot/1.0 (+https://github.com/w0rxbend/telegram-weather-bot)",
        ),
    )
