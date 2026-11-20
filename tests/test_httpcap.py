import httpx
import pytest

from weather_bot.httpcap import ResponseTooLargeError, get_capped, parse_json


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_returns_small_body_with_status_and_json() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    async with _client(transport) as client:
        response = await get_capped(client, "https://example.test/x", params={"a": 1})
    assert response.json() == {"ok": True}
    response.raise_for_status()


async def test_error_status_is_preserved() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    async with _client(transport) as client:
        response = await get_capped(client, "https://example.test/x")
    assert response.status_code == 503


async def test_rejects_declared_oversize() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 50))
    async with _client(transport) as client:
        with pytest.raises(ResponseTooLargeError):
            await get_capped(client, "https://example.test/x", max_bytes=10)


async def test_rejects_streamed_oversize_without_length() -> None:
    async def body():  # type: ignore[no-untyped-def]
        for _ in range(5):
            yield b"x" * 10

    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=body()))
    async with _client(transport) as client:
        with pytest.raises(ResponseTooLargeError):
            await get_capped(client, "https://example.test/x", max_bytes=25)


@pytest.mark.parametrize(
    "body",
    [
        b'{"t": NaN}',
        b'{"t": Infinity}',
        b'{"t": -Infinity}',
        b'{"t": 1e999}',
        b"[1" + b"0" * 400 + b"]",
    ],
)
def test_parse_json_rejects_non_finite_numbers(body: bytes) -> None:
    # json.loads accepts all of these; they later crashed round() in handlers (F-53)
    with pytest.raises(ValueError):
        parse_json(httpx.Response(200, content=body))


def test_parse_json_decodes_ordinary_json() -> None:
    body = b'{"a": 1.5, "b": -3, "c": [null, true, "x"], "d": 9007199254740993}'
    assert parse_json(httpx.Response(200, content=body)) == {
        "a": 1.5,
        "b": -3,
        "c": [None, True, "x"],
        "d": 9007199254740993,
    }
