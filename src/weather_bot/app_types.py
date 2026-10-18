"""Shared type aliases for the PTB application (kept free of weather_bot imports)."""

from __future__ import annotations

from typing import Any

from telegram.ext import Application

App = Application[Any, Any, Any, Any, Any, Any]
