"""Process-wide runtime objects that must never end up in persisted bot_data.

The persistence layer serialises ``bot_data`` as a whole; an httpx client in there makes
the dump fail, which truncates the single state file and breaks the next startup.
"""

from __future__ import annotations

from typing import Any

import httpx
from telegram.ext import Application

from weather_bot.ratelimit import MinIntervalGate
from weather_bot.telemetry import UsageTelemetry

App = Application[Any, Any, Any, Any, Any, Any]  # PTB application with default context types

NOMINATIM_INTERVAL = 1.0  # Nominatim usage policy: at most one request per second

_http: httpx.AsyncClient | None = None
_nominatim_gate: MinIntervalGate | None = None


def set_http(client: httpx.AsyncClient | None) -> None:
    global _http
    _http = client


def http() -> httpx.AsyncClient:
    if _http is None:
        raise RuntimeError("HTTP client is not initialised")
    return _http


def nominatim_gate() -> MinIntervalGate:
    """Shared gate for Nominatim; built on first use because its lock binds to the event loop."""
    global _nominatim_gate
    if _nominatim_gate is None:
        _nominatim_gate = MinIntervalGate(NOMINATIM_INTERVAL)
    return _nominatim_gate


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
