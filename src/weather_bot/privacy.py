"""Helpers that keep personal data (coordinates, typed city names, message text) out of logs."""

from __future__ import annotations

import httpx


def describe_error(exc: BaseException) -> str:
    """Short, URL-free description of an error.

    ``str(httpx.HTTPError)`` embeds the request URL, which carries the user's coordinates
    or typed city name as query parameters.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return type(exc).__name__
    return str(exc)
