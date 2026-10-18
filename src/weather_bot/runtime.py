"""Process-wide runtime objects that must never end up in persisted bot_data.

PTB's PicklePersistence pickles ``bot_data`` as a whole; an httpx client in there makes
the dump fail, which truncates the single state file and breaks the next startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from weather_bot.ratelimit import Cooldown, MinIntervalGate

CARD_COOLDOWN_SECONDS = 2.0
NOMINATIM_INTERVAL_SECONDS = 1.0  # Nominatim usage policy: max one request per second


@dataclass
class _State:
    http: httpx.AsyncClient | None = None
    cooldown: Cooldown = field(default_factory=lambda: Cooldown(CARD_COOLDOWN_SECONDS))
    # created lazily: an asyncio.Lock binds to the running event loop
    nominatim_gate: MinIntervalGate | None = None


_state = _State()


def set_http(client: httpx.AsyncClient | None) -> None:
    _state.http = client


def http() -> httpx.AsyncClient:
    if _state.http is None:
        raise RuntimeError("HTTP client is not initialised")
    return _state.http


def cooldown() -> Cooldown:
    return _state.cooldown


def nominatim_gate() -> MinIntervalGate:
    if _state.nominatim_gate is None:
        _state.nominatim_gate = MinIntervalGate(NOMINATIM_INTERVAL_SECONDS)
    return _state.nominatim_gate


def reset() -> None:
    """Forget all process-wide state (used by tests)."""
    global _state  # noqa: PLW0603 - reset() rebinds the single state holder
    _state = _State()
