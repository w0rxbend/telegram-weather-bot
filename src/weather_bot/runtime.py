"""Process-wide runtime objects that must never end up in persisted bot_data.

PTB's PicklePersistence pickles ``bot_data`` as a whole; an httpx client in there makes
the dump fail, which truncates the single state file and breaks the next startup.
"""

from __future__ import annotations

import httpx

_http: httpx.AsyncClient | None = None


def set_http(client: httpx.AsyncClient | None) -> None:
    global _http
    _http = client


def http() -> httpx.AsyncClient:
    if _http is None:
        raise RuntimeError("HTTP client is not initialised")
    return _http
