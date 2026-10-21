"""Geocoding helpers.

* Reverse geocoding (coordinates -> place name) uses Nominatim / OpenStreetMap.
  Nominatim's usage policy requires an identifying User-Agent and at most one request
  per second across all users, so callers pass a ``MinIntervalGate`` to space them out.
* Forward geocoding (city name -> coordinates) uses Open-Meteo's geocoding API, for people
  on clients that cannot share a location (for example Telegram Desktop).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from weather_bot.httpcap import get_capped
from weather_bot.privacy import describe_error
from weather_bot.ratelimit import MinIntervalGate

log = logging.getLogger(__name__)

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


@dataclass(frozen=True)
class Place:
    name: str
    latitude: float
    longitude: float

    @property
    def coords_label(self) -> str:
        return f"{self.latitude:.3f}, {self.longitude:.3f}"


def _pick_locality(address: dict[str, str]) -> str | None:
    for key in ("city", "town", "village", "municipality", "hamlet", "suburb", "county", "state"):
        if address.get(key):
            return address[key]
    return None


async def reverse_geocode(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    language: str | None = None,
    gate: MinIntervalGate | None = None,
) -> Place:
    """Return a human-readable place for the coordinates; never raises.

    ``gate`` spaces calls out to respect Nominatim's one-request-per-second policy.
    """
    fallback = Place(
        name=f"{latitude:.3f}, {longitude:.3f}", latitude=latitude, longitude=longitude
    )
    params: dict[str, str | int] = {
        "lat": f"{latitude:.6f}",
        "lon": f"{longitude:.6f}",
        "format": "jsonv2",
        "zoom": 12,
    }
    headers = {"Accept-Language": language or "en"}
    if gate is not None:
        await gate.wait()
    try:
        response = await get_capped(client, NOMINATIM_REVERSE_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Reverse geocoding failed: %s", describe_error(exc))
        return fallback

    address = data.get("address") or {}
    locality = _pick_locality(address)
    country = address.get("country")
    if locality and country and locality != country:
        name = f"{locality}, {country}"
    else:
        name = locality or country or data.get("name") or fallback.name
    return Place(name=name, latitude=latitude, longitude=longitude)


async def search_place(
    client: httpx.AsyncClient, query: str, language: str | None = None
) -> Place | None:
    """Find the best match for a typed city name, or ``None`` when nothing matches."""
    params: dict[str, str | int] = {
        "name": query.strip(),
        "count": 1,
        "language": (language or "en")[:2],
        "format": "json",
    }
    try:
        response = await get_capped(client, OPEN_METEO_GEOCODE_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Forward geocoding failed: %s", describe_error(exc))
        return None

    results = data.get("results") or []
    if not results:
        return None
    hit = results[0]
    parts = [hit.get("name")]
    if hit.get("admin1") and hit.get("admin1") != hit.get("name"):
        parts.append(hit["admin1"])
    if hit.get("country"):
        parts.append(hit["country"])
    return Place(
        name=", ".join(p for p in parts if p),
        latitude=float(hit["latitude"]),
        longitude=float(hit["longitude"]),
    )


SEARCH_CACHE_TTL = 3600.0  # city -> coordinates changes about never; an hour keeps the data fresh
SEARCH_CACHE_MAX = 512
_search_cache: OrderedDict[tuple[str, str], tuple[float, Place]] = OrderedDict()


async def search_place_cached(
    client: httpx.AsyncClient,
    query: str,
    language: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Place | None:
    """``search_place`` with a small in-memory cache for repeated queries.

    Only hits are cached: ``search_place`` returns ``None`` both for "no such place" and for a
    failed request, and a transient outage must not stick for an hour. This matters for inline
    mode, where one search fires a query per pause in typing and many users look up the same
    cities. State resets on restart.
    """
    key = (" ".join(query.casefold().split()), language or "")
    now = clock()
    cached = _search_cache.get(key)
    if cached is not None and now - cached[0] < SEARCH_CACHE_TTL:
        _search_cache.move_to_end(key)
        return cached[1]
    place = await search_place(client, query, language)
    if place is not None:
        _search_cache[key] = (now, place)
        _search_cache.move_to_end(key)
        while len(_search_cache) > SEARCH_CACHE_MAX:
            _search_cache.popitem(last=False)
    return place
