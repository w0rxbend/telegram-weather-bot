"""Process-wide runtime objects that must never end up in persisted bot_data.

The persistence layer serialises ``bot_data`` as a whole; an httpx client in there makes
the dump fail, which truncates the single state file and breaks the next startup.
"""

from __future__ import annotations

from typing import Any

import httpx
from telegram.ext import Application

from weather_bot.ratelimit import MinIntervalGate

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
