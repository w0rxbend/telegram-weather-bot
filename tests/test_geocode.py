from __future__ import annotations

import json

import httpx
import pytest

from weather_bot import geocode
from weather_bot.geocode import (
    SEARCH_CACHE_TTL,
    reverse_geocode,
    search_place,
    search_place_cached,
)
from weather_bot.httpcap import MAX_RESPONSE_BYTES
from weather_bot.ratelimit import MinIntervalGate


async def test_reverse_geocode_builds_city_country() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-language"] == "uk"
        return httpx.Response(200, json={"address": {"city": "Київ", "country": "Україна"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        place = await reverse_geocode(client, 50.45, 30.52, "uk")
    assert place.name == "Київ, Україна"
    assert (place.latitude, place.longitude) == (50.45, 30.52)


async def test_reverse_geocode_prefers_most_specific_locality() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"address": {"village": "Hobbiton", "county": "Shire", "country": "NZ"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        place = await reverse_geocode(client, 1, 2)
    assert place.name == "Hobbiton, NZ"


async def test_reverse_geocode_falls_back_to_coordinates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        place = await reverse_geocode(client, 12.3456, -7.891)
    assert place.name == "12.346, -7.891"


async def test_search_place() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == "Lviv"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Lviv",
                        "admin1": "Lviv Oblast",
                        "country": "Ukraine",
                        "latitude": 49.84,
                        "longitude": 24.03,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        place = await search_place(client, "  Lviv ")
    assert place is not None
    assert place.name == "Lviv, Lviv Oblast, Ukraine"
    assert place.latitude == 49.84


async def test_search_place_no_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"generationtime_ms": 0.1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await search_place(client, "zzzzzz") is None


async def test_reverse_geocode_spaces_requests_through_the_gate() -> None:
    events: list[str] = []
    now = [0.0]

    async def sleep(delay: float) -> None:
        events.append(f"sleep {delay}")
        now[0] += delay

    def handler(request: httpx.Request) -> httpx.Response:
        events.append("request")
        return httpx.Response(200, json={"address": {"city": "Kyiv", "country": "Ukraine"}})

    gate = MinIntervalGate(1.0, clock=lambda: now[0], sleep=sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await reverse_geocode(client, 50.45, 30.52, gate=gate)
        await reverse_geocode(client, 49.84, 24.03, gate=gate)
    assert events == ["request", "sleep 1.0", "request"]


async def test_oversized_reverse_geocode_response_falls_back_to_coordinates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        city = b"x" * MAX_RESPONSE_BYTES
        return httpx.Response(200, content=b'{"address": {"city": "' + city + b'"}}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        place = await reverse_geocode(client, 12.3456, -7.891)
    assert place.name == "12.346, -7.891"


async def test_oversized_search_response_counts_as_not_found() -> None:
    hit = {
        "results": [{"name": "Lviv", "country": "Ukraine", "latitude": 49.84, "longitude": 24.03}]
    }
    padding = b" " * (MAX_RESPONSE_BYTES + 1)  # keeps the JSON valid: only the size cap rejects it

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(hit).encode() + padding)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await search_place(client, "Kyiv") is None


@pytest.fixture(autouse=True)
def _empty_search_cache() -> None:
    geocode._search_cache.clear()


def _hit(name: str = "Lviv") -> dict:
    return {
        "results": [{"name": name, "country": "Ukraine", "latitude": 49.84, "longitude": 24.03}]
    }


async def test_search_place_cached_reuses_a_hit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_hit())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await search_place_cached(client, "Lviv", "uk")
        again = await search_place_cached(client, "  LVIV ", "uk")  # same place, other spelling
        await search_place_cached(client, "Lviv", "en")  # the language is part of the key
    assert first is not None and first == again
    assert calls == 2


async def test_search_place_cached_does_not_cache_misses() -> None:
    answers = [{"generationtime_ms": 0.1}, _hit()]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=answers[calls - 1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await search_place_cached(client, "Lviv") is None  # also what an outage returns
        assert await search_place_cached(client, "Lviv") is not None
    assert calls == 2


async def test_search_place_cached_expires_entries() -> None:
    now = [0.0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_hit())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await search_place_cached(client, "Lviv", clock=lambda: now[0])
        now[0] = SEARCH_CACHE_TTL - 1
        await search_place_cached(client, "Lviv", clock=lambda: now[0])
        assert calls == 1
        now[0] = SEARCH_CACHE_TTL + 1
        await search_place_cached(client, "Lviv", clock=lambda: now[0])
    assert calls == 2


async def test_search_place_cached_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocode, "SEARCH_CACHE_MAX", 2)
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params["name"]
        fetched.append(name)
        return httpx.Response(200, json=_hit(name))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for name in ("Aaa", "Bbb", "Ccc"):
            await search_place_cached(client, name)
        await search_place_cached(client, "Ccc")  # still cached
        await search_place_cached(client, "Aaa")  # evicted by Ccc, fetched again
    assert fetched == ["Aaa", "Bbb", "Ccc", "Aaa"]
