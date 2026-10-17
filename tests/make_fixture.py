"""Build a deterministic Open-Meteo-shaped payload for tests and previews.

Run ``python tests/make_fixture.py`` to regenerate ``tests/fixtures/forecast.json``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

START = datetime(2026, 10, 17, 0, 0)
NOW = datetime(2026, 10, 17, 14, 15)

HOURLY_CODES = [3, 3, 61, 61, 63, 61, 3, 2, 2, 1, 0, 0, 0, 1, 2, 2, 3, 80, 80, 95, 61, 3, 3, 3]
DAILY = [
    # code, tmax, tmin, uv, prob, sum
    (80, 17.4, 9.1, 3.2, 70, 4.1),
    (2, 19.0, 8.0, 3.8, 10, 0.0),
    (0, 21.5, 9.5, 4.1, 0, 0.0),
    (61, 14.2, 7.7, 1.9, 85, 9.6),
    (71, 3.0, -2.4, 1.0, 60, 2.2),
    (45, 6.5, 0.2, 1.4, 20, 0.0),
    (95, 12.8, 5.0, 2.0, 90, 12.3),
]


def build() -> dict:
    hours = 24 * 7
    times, temps, probs, codes, is_day = [], [], [], [], []
    for h in range(hours):
        t = START + timedelta(hours=h)
        hour = t.hour
        day_index = h // 24
        base = (DAILY[day_index][1] + DAILY[day_index][2]) / 2
        amp = (DAILY[day_index][1] - DAILY[day_index][2]) / 2
        temp = base + amp * math.sin((hour - 9) / 24 * 2 * math.pi)
        code = HOURLY_CODES[hour] if day_index == 0 else DAILY[day_index][0]
        prob = {61: 70, 63: 85, 80: 60, 95: 90, 71: 55}.get(code, 10 if code >= 2 else 0)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        temps.append(round(temp, 1))
        probs.append(prob)
        codes.append(code)
        is_day.append(1 if 7 <= hour < 18 else 0)

    daily_time, dcode, tmax, tmin, rise, sset, uv, dprob, dsum = ([] for _ in range(9))
    for i, (code, hi, lo, uvi, prob, psum) in enumerate(DAILY):
        d = START + timedelta(days=i)
        daily_time.append(d.strftime("%Y-%m-%d"))
        dcode.append(code)
        tmax.append(hi)
        tmin.append(lo)
        rise.append(d.replace(hour=7, minute=12 + i).strftime("%Y-%m-%dT%H:%M"))
        sset.append(d.replace(hour=17, minute=59 - 2 * i).strftime("%Y-%m-%dT%H:%M"))
        uv.append(uvi)
        dprob.append(prob)
        dsum.append(psum)

    return {
        "latitude": 50.45,
        "longitude": 30.52,
        "utc_offset_seconds": 10800,
        "timezone": "Europe/Kyiv",
        "timezone_abbreviation": "GMT+3",
        "elevation": 169.0,
        "current": {
            "time": NOW.strftime("%Y-%m-%dT%H:%M"),
            "interval": 900,
            "temperature_2m": 15.6,
            "apparent_temperature": 13.9,
            "relative_humidity_2m": 72,
            "is_day": 1,
            "precipitation": 0.3,
            "weather_code": 80,
            "cloud_cover": 64,
            "pressure_msl": 1012.4,
            "wind_speed_10m": 14.3,
            "wind_direction_10m": 305,
            "wind_gusts_10m": 31.0,
        },
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "precipitation_probability": probs,
            "weather_code": codes,
            "is_day": is_day,
        },
        "daily": {
            "time": daily_time,
            "weather_code": dcode,
            "temperature_2m_max": tmax,
            "temperature_2m_min": tmin,
            "sunrise": rise,
            "sunset": sset,
            "uv_index_max": uv,
            "precipitation_probability_max": dprob,
            "precipitation_sum": dsum,
        },
    }


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures" / "forecast.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(build(), indent=1))
    print(f"wrote {out}")
