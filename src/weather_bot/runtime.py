"""Process-wide runtime objects that must never end up in persisted bot_data.

The persistence layer serialises ``bot_data`` as a whole; an httpx client in there makes
the dump fail, which truncates the single state file and breaks the next startup.
"""

from __future__ import annotations

from typing import Any

import httpx
from telegram.ext import Application

from weather_bot.telemetry import UsageTelemetry

App = Application[Any, Any, Any, Any, Any, Any]  # PTB application with default context types

_http: httpx.AsyncClient | None = None


def set_http(client: httpx.AsyncClient | None) -> None:
    global _http
    _http = client


def http() -> httpx.AsyncClient:
    if _http is None:
        raise RuntimeError("HTTP client is not initialised")
    return _http


_telemetry: UsageTelemetry | None = None
_admin_ids: frozenset[int] = frozenset()


def set_telemetry(telemetry: UsageTelemetry | None) -> None:
    global _telemetry
    _telemetry = telemetry


def telemetry() -> UsageTelemetry | None:
    """The usage recorder, or ``None`` when telemetry is not configured (e.g. in tests)."""
    return _telemetry


def set_admin_ids(ids: frozenset[int]) -> None:
    global _admin_ids
    _admin_ids = ids


def is_admin(user_id: int) -> bool:
    return user_id in _admin_ids


def admin_ids() -> frozenset[int]:
    return _admin_ids
