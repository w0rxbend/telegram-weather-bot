from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from weather_bot import cache as cache_mod
from weather_bot.cache import ForecastCache
from weather_bot.weather import Forecast, WeatherError


def make_client(payload: dict, counter: list[int], fail: bool = False) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, content=json.dumps(payload))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_hit_within_ttl_and_rounding(payload: dict) -> None:
    calls: list[int] = []
    cache = ForecastCache(ttl=3600)
    async with make_client(payload, calls) as client:
        a = await cache.get(client, 50.4501, 30.5199)
        b = await cache.get(client, 50.4504, 30.5203)  # same 2-decimal cell
        c = await cache.get(client, 50.4501, 30.5199, "imperial")  # different units
    assert a is b and a is not c
    assert len(calls) == 2
    assert cache.hits == 1 and cache.misses == 2
    assert cache.peek(50.45, 30.52, "metric") is a


async def test_miss_after_ttl(payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    cache = ForecastCache(ttl=10)
    clock = [1000.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock[0])
    async with make_client(payload, calls) as client:
        await cache.get(client, 50.45, 30.52)
        clock[0] += 9
        await cache.get(client, 50.45, 30.52)
        assert len(calls) == 1
        clock[0] += 2
        await cache.get(client, 50.45, 30.52)
        assert len(calls) == 2


async def test_concurrent_requests_share_one_call(payload: dict) -> None:
    calls: list[int] = []
    cache = ForecastCache()
    async with make_client(payload, calls) as client:
        results = await asyncio.gather(*(cache.get(client, 50.45, 30.52) for _ in range(8)))
    assert len(calls) == 1
    assert all(r is results[0] for r in results)


async def test_stale_served_on_error(payload: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from weather_bot import weather

    monkeypatch.setattr(weather, "RETRY_DELAYS", (0,))
    calls: list[int] = []
    cache = ForecastCache(ttl=10)
    clock = [1000.0]
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock[0])
    async with make_client(payload, calls) as client:
        fresh = await cache.get(client, 50.45, 30.52)
    clock[0] += 60
    async with make_client(payload, calls, fail=True) as broken:
        assert await cache.get(broken, 50.45, 30.52) is fresh  # stale fallback
        clock[0] += cache_mod.STALE_TTL + 1
        with pytest.raises(WeatherError):
            await cache.get(broken, 50.45, 30.52)


def test_eviction(forecast: Forecast) -> None:
    cache = ForecastCache(max_entries=2)
    for i in range(3):
        cache.put(float(i), 0.0, "metric", forecast)
    assert len(cache) == 2
    assert cache.peek(0.0, 0.0, "metric") is None
    assert cache.peek(2.0, 0.0, "metric") is forecast


async def test_waiters_are_released_when_the_fetch_is_cancelled(payload: dict) -> None:
    started = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never answers
        raise AssertionError

    async def slow_fetch(*_args: object) -> Forecast:
        started.set()
        await asyncio.sleep(3600)
        raise AssertionError

    cache = ForecastCache()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        original = cache_mod.fetch_forecast
        cache_mod.fetch_forecast = slow_fetch  # type: ignore[assignment]
        try:
            first = asyncio.create_task(cache.get(client, 50.45, 30.52))
            await started.wait()
            waiter = asyncio.create_task(cache.get(client, 50.45, 30.52))
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(WeatherError):
                await asyncio.wait_for(waiter, timeout=2)
        finally:
            cache_mod.fetch_forecast = original
