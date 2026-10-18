"""In-memory forecast cache: one Open-Meteo call per place, per units, per hour.

* Coordinates are rounded to two decimals (~1 km), so nearby requests share an entry.
* Entries are fresh for ``ttl`` seconds (default one hour, ``FORECAST_CACHE_TTL`` env).
* Concurrent requests for the same key are coalesced into a single API call.
* If the API fails and a stale entry (< ``stale_ttl``) exists, that entry is served instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

from weather_bot.weather import Forecast, Units, WeatherError, fetch_forecast

log = logging.getLogger(__name__)

DEFAULT_TTL = float(os.getenv("FORECAST_CACHE_TTL", "3600"))
STALE_TTL = 6 * 3600
MAX_ENTRIES = 5000
KEY_PRECISION = 2  # decimals of latitude/longitude


@dataclass
class Entry:
    forecast: Forecast
    fetched_at: float


class ForecastCache:
    def __init__(self, ttl: float = DEFAULT_TTL, max_entries: int = MAX_ENTRIES) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[float, float, str], Entry] = OrderedDict()
        self._pending: dict[tuple[float, float, str], asyncio.Future[Forecast]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(latitude: float, longitude: float, units: Units) -> tuple[float, float, str]:
        return round(latitude, KEY_PRECISION), round(longitude, KEY_PRECISION), units

    def peek(self, latitude: float, longitude: float, units: Units) -> Forecast | None:
        """Fresh entry or None (no network)."""
        entry = self._entries.get(self.key(latitude, longitude, units))
        if entry and time.monotonic() - entry.fetched_at < self.ttl:
            return entry.forecast
        return None

    def put(self, latitude: float, longitude: float, units: Units, forecast: Forecast) -> None:
        key = self.key(latitude, longitude, units)
        self._entries[key] = Entry(forecast, time.monotonic())
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    async def get(
        self, client: httpx.AsyncClient, latitude: float, longitude: float, units: Units = "metric"
    ) -> Forecast:
        key = self.key(latitude, longitude, units)
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry and now - entry.fetched_at < self.ttl:
            self.hits += 1
            return entry.forecast

        pending = self._pending.get(key)
        if pending is not None:  # someone is already fetching this place: wait for them
            self.hits += 1
            return await pending

        self.misses += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Forecast] = loop.create_future()
        self._pending[key] = future
        try:
            forecast = await fetch_forecast(client, key[0], key[1], units)
        except WeatherError as exc:
            if entry and now - entry.fetched_at < STALE_TTL:
                log.warning("Serving stale forecast for %s after error: %s", key, exc)
                future.set_result(entry.forecast)
                return entry.forecast
            future.set_exception(exc)
            raise
        else:
            self.put(key[0], key[1], units, forecast)
            future.set_result(forecast)
            return forecast
        finally:
            self._pending.pop(key, None)


_cache = ForecastCache()


def forecast_cache() -> ForecastCache:
    return _cache


async def cached_forecast(
    client: httpx.AsyncClient, latitude: float, longitude: float, units: Units = "metric"
) -> Forecast:
    return await _cache.get(client, latitude, longitude, units)
