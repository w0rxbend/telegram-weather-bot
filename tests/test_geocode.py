from __future__ import annotations

import httpx

from weather_bot.geocode import reverse_geocode, search_place
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
