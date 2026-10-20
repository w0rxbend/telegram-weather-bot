"""Bounded reads of outbound HTTP responses."""

from __future__ import annotations

import json
from typing import Any

import httpx

MAX_RESPONSE_BYTES = 512 * 1024  # real forecasts are ~20 KB; this only stops runaway bodies


class ResponseTooLargeError(httpx.HTTPError):
    """The upstream body exceeded the allowed size."""


async def read_json_capped(response: httpx.Response, max_bytes: int = MAX_RESPONSE_BYTES) -> Any:
    """Read a streamed response body without buffering more than ``max_bytes``."""
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdecimal() and int(declared) > max_bytes:
        raise ResponseTooLargeError("response too large")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ResponseTooLargeError("response too large")
    return json.loads(body)
