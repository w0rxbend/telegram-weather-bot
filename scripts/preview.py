"""Render a preview card without Telegram.

Usage:
    python scripts/preview.py                       # Kyiv, metric
    python scripts/preview.py 51.5 -0.12 London     # any coordinates + label
    python scripts/preview.py --units imperial 40.71 -74.0 "New York"
    python scripts/preview.py --fixture tests/fixtures/forecast.json
    python scripts/preview.py --out out.png ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx  # noqa: E402

from weather_bot.render import render_card  # noqa: E402
from weather_bot.weather import fetch_forecast, parse_forecast  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", nargs="?", type=float, default=50.45)
    ap.add_argument("lon", nargs="?", type=float, default=30.52)
    ap.add_argument("name", nargs="?", default="Kyiv, Ukraine")
    ap.add_argument("--units", choices=["metric", "imperial"], default="metric")
    ap.add_argument("--fixture", type=Path, help="Render from a saved Open-Meteo JSON payload")
    ap.add_argument("--out", type=Path, default=Path("preview.png"))
    args = ap.parse_args()

    now = None
    if args.fixture:
        forecast = parse_forecast(json.loads(args.fixture.read_text()), args.units)
        now = forecast.observed_at  # deterministic output for fixtures
    else:
        async with httpx.AsyncClient(timeout=20) as client:
            forecast = await fetch_forecast(client, args.lat, args.lon, args.units)

    args.out.write_bytes(render_card(forecast, args.name, now))
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    asyncio.run(main())
