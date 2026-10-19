"""Runtime configuration read from environment variables (and an optional .env file)."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    data_dir: Path
    http_timeout: float
    user_agent: str
    forecast_cache_ttl: float

    @property
    def persistence_file(self) -> Path:
        return self.data_dir / "bot_state.pickle"


def _positive_float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number, got {raw!r}.") from None
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(f"{name} must be a positive number, got {raw!r}.")
    return value


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN is not set. Put it in the environment or in a .env file.")

    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        data_dir=data_dir,
        http_timeout=_positive_float("HTTP_TIMEOUT", "15"),
        user_agent=os.getenv(
            "USER_AGENT",
            "telegram-weather-bot/1.0 (+https://github.com/w0rxbend/telegram-weather-bot)",
        ),
        forecast_cache_ttl=_positive_float("FORECAST_CACHE_TTL", "3600"),
    )
