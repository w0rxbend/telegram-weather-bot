"""Process-wide runtime objects that must never end up in persisted bot_data.

The persistence layer serialises ``bot_data`` as a whole; an httpx client in there makes
the dump fail, which truncates the single state file and breaks the next startup.
"""

from __future__ import annotations

from typing import Any

import httpx
from telegram.ext import Application

App = Application[Any, Any, Any, Any, Any, Any]  # PTB application with default context types

_http: httpx.AsyncClient | None = None


def set_http(client: httpx.AsyncClient | None) -> None:
    global _http
    _http = client


def http() -> httpx.AsyncClient:
    if _http is None:
        raise RuntimeError("HTTP client is not initialised")
    return _http
