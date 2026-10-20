from __future__ import annotations

import httpx

from weather_bot.geocode import reverse_geocode, search_place


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


async def test_oversized_geocode_response_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"address": {"city": "' + b"x" * 600_000 + b'"}}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        place = await reverse_geocode(client, 12.3456, -7.891)
    assert place.name == "12.346, -7.891"
