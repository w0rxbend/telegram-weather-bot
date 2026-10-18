"""Colour palettes keyed by weather condition and day/night."""

from __future__ import annotations

from dataclasses import dataclass

from weather_bot.weather import IconKind
import itertools

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    top: RGB
    bottom: RGB
    glow_a: RGB
    glow_b: RGB


_DAY: dict[IconKind, Theme] = {
    "clear": Theme((26, 92, 214), (96, 178, 255), (255, 196, 80), (120, 210, 255)),
    "mostly-clear": Theme((30, 96, 205), (104, 172, 240), (255, 200, 90), (150, 215, 255)),
    "partly-cloudy": Theme((36, 95, 190), (118, 165, 222), (255, 205, 110), (190, 220, 255)),
    "overcast": Theme((62, 78, 104), (120, 136, 162), (200, 210, 230), (150, 170, 200)),
    "fog": Theme((88, 100, 122), (150, 160, 178), (220, 225, 235), (170, 180, 200)),
    "drizzle": Theme((44, 72, 110), (92, 124, 166), (140, 190, 240), (90, 140, 200)),
    "rain": Theme((38, 64, 102), (84, 118, 160), (120, 180, 240), (80, 130, 200)),
    "heavy-rain": Theme((28, 46, 76), (62, 88, 124), (110, 160, 220), (60, 100, 160)),
    "snow": Theme((86, 118, 156), (166, 196, 226), (240, 248, 255), (180, 210, 240)),
    "showers": Theme((40, 80, 136), (96, 146, 196), (255, 210, 120), (120, 180, 240)),
    "snow-showers": Theme((92, 124, 164), (170, 200, 230), (255, 245, 220), (190, 215, 245)),
    "thunder": Theme((40, 36, 84), (92, 76, 140), (255, 214, 80), (150, 120, 220)),
}

_NIGHT: dict[IconKind, Theme] = {
    "clear": Theme((10, 16, 44), (34, 48, 100), (190, 200, 255), (90, 110, 200)),
    "mostly-clear": Theme((12, 20, 50), (38, 54, 108), (190, 200, 255), (90, 120, 210)),
    "partly-cloudy": Theme((16, 24, 54), (46, 62, 112), (180, 195, 250), (100, 130, 210)),
    "overcast": Theme((24, 30, 44), (52, 62, 84), (150, 165, 200), (90, 105, 140)),
    "fog": Theme((34, 40, 54), (70, 80, 100), (180, 190, 210), (110, 120, 150)),
    "drizzle": Theme((18, 28, 46), (42, 58, 86), (110, 150, 210), (60, 100, 170)),
    "rain": Theme((14, 22, 38), (36, 50, 76), (100, 140, 200), (50, 90, 160)),
    "heavy-rain": Theme((10, 16, 30), (28, 40, 62), (90, 130, 190), (40, 80, 150)),
    "snow": Theme((30, 44, 66), (72, 94, 124), (220, 235, 255), (130, 160, 210)),
    "showers": Theme((16, 28, 50), (44, 66, 104), (120, 160, 230), (70, 110, 190)),
    "snow-showers": Theme((32, 48, 72), (78, 102, 136), (230, 240, 255), (140, 170, 220)),
    "thunder": Theme((14, 12, 40), (48, 36, 92), (255, 214, 80), (130, 100, 210)),
}


def theme_for(kind: IconKind, is_day: bool) -> Theme:
    table = _DAY if is_day else _NIGHT
    return table.get(kind, table["overcast"])


# Temperature -> colour ramp (Celsius thresholds), used for the hourly curve and daily bars.
_TEMP_STOPS: list[tuple[float, RGB]] = [
    (-25.0, (150, 170, 255)),
    (-10.0, (110, 180, 255)),
    (0.0, (90, 210, 255)),
    (8.0, (80, 225, 205)),
    (15.0, (170, 235, 120)),
    (21.0, (255, 220, 90)),
    (27.0, (255, 165, 70)),
    (33.0, (255, 105, 80)),
    (40.0, (255, 70, 110)),
]


def temp_colour(value: float, imperial: bool = False) -> RGB:
    celsius = (value - 32) * 5 / 9 if imperial else value
    stops = _TEMP_STOPS
    if celsius <= stops[0][0]:
        return stops[0][1]
    if celsius >= stops[-1][0]:
        return stops[-1][1]
    for (t0, c0), (t1, c1) in itertools.pairwise(stops):
        if t0 <= celsius <= t1:
            k = (celsius - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1, strict=True))  # type: ignore[return-value]
    return stops[-1][1]


def uv_label(uv: float) -> str:
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very high"
    return "Extreme"


def pressure_label(hpa: float) -> str:
    if hpa < 1000:
        return "Low"
    if hpa > 1025:
        return "High"
    return "Normal"


WHITE: RGB = (255, 255, 255)
RAIN_BLUE: RGB = (130, 200, 255)
SUN_YELLOW: RGB = (255, 206, 84)
