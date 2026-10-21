"""GET helper that refuses oversized responses before buffering them in memory."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

MAX_RESPONSE_BYTES = 1_000_000  # forecasts are ~30 KB; geocoding replies are smaller


class ResponseTooLargeError(httpx.HTTPError):
    """The upstream body exceeded the allowed size."""


async def get_capped(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str | int] | None = None,
    headers: Mapping[str, str] | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """GET ``url`` and return a fully read response, raising once the body passes ``max_bytes``."""
    async with client.stream("GET", url, params=params, headers=headers) as response:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise ResponseTooLargeError("response too large")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > max_bytes:
                raise ResponseTooLargeError("response too large")
        return httpx.Response(
            response.status_code,
            content=bytes(body),
            headers={"content-type": response.headers.get("content-type", "")},
            request=response.request,
        )
