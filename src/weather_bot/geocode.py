"""Geocoding helpers.

* Reverse geocoding (coordinates -> place name) uses Nominatim / OpenStreetMap.
  Nominatim's usage policy requires an identifying User-Agent and at most one request
  per second; the bot only calls it once per setup, so that is comfortably within limits.
* Forward geocoding (city name -> coordinates) uses Open-Meteo's geocoding API, for people
  on clients that cannot share a location (for example Telegram Desktop).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

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
    params = {"lat": f"{latitude:.6f}", "lon": f"{longitude:.6f}", "format": "jsonv2", "zoom": 12}
    headers = {"Accept-Language": language or "en"}
    if gate is not None:
        await gate.wait()
    try:
        response = await client.get(NOMINATIM_REVERSE_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Reverse geocoding failed: %s", exc)
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
    params = {
        "name": query.strip(),
        "count": 1,
        "language": (language or "en")[:2],
        "format": "json",
    }
    try:
        response = await client.get(OPEN_METEO_GEOCODE_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Forward geocoding failed: %s", exc)
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
