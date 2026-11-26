"""Upstream HTTP helpers: a size-capped GET and a JSON decoder that refuses NaN and infinity."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

import httpx

MAX_RESPONSE_BYTES = 1_000_000  # forecasts are ~30 KB; geocoding replies are smaller
MAX_JSON_INT = 2**63  # far above any id or value the upstream APIs send


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


def _reject_constant(name: str) -> float:
    raise ValueError(f"non-finite number {name} in JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # e.g. 1e999 decodes to inf
        raise ValueError("non-finite number in JSON")
    return value


def _bounded_int(text: str) -> int:
    value = int(text)
    if abs(value) > MAX_JSON_INT:  # float() of a 309-digit integer raises OverflowError
        raise ValueError("integer out of range in JSON")
    return value


def parse_json(response: httpx.Response) -> Any:
    """Decode a JSON body like ``response.json()``, but raise ``ValueError`` on NaN or infinity.

    Python's ``json`` accepts ``NaN``, ``Infinity`` and ``1e999`` (decoded as inf). Such values
    pass ``float()`` and later crash ``round()``/``int()`` in a handler. Raising ``ValueError``
    lets callers treat them like any other invalid JSON.
    """
    return json.loads(
        response.content,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        parse_int=_bounded_int,
    )
