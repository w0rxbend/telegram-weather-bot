"""Sun-path arc: a semicircle from sunrise (left) to sunset (right) with the sun on it.

Shared by the small tile on the weather card and the hero graphic on the sun card.
"""

from __future__ import annotations

import math

from PIL import ImageDraw, ImageFilter

from weather_bot.render.card import Canvas, _alpha
from weather_bot.render.theme import RGB, WHITE
from weather_bot.sun import SunInfo

SUN_RGB: RGB = (255, 204, 77)
MOON_RGB: RGB = (226, 232, 250)


def _point(cx: float, cy: float, rx: float, ry: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return cx + rx * math.cos(a), cy + ry * math.sin(a)


def _dashed_arc(
    c: Canvas,
    layer_draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    start: float,
    end: float,
    width: float,
    fill: tuple[int, int, int, int],
    dash: float = 7.0,
) -> None:
    """Pillow has no dashed arcs, so draw short arc segments."""
    bbox = c.box(cx - rx, cy - ry, cx + rx, cy + ry)
    circumference = math.pi * (rx + ry)  # ~ half-ellipse approximation per 180°
    step = max(2.0, dash / max(circumference, 1) * 180)
    angle = start
    while angle < end:
        seg_end = min(angle + step, end)
        layer_draw.arc(bbox, angle, seg_end, fill=fill, width=c.px(width))
        angle += step * 1.8


def draw_sun_path(
    c: Canvas,
    info: SunInfo,
    cx: float,
    cy: float,
    r: float,
    *,
    stroke: float = 4.0,
    sun_radius: float = 12.0,
    night_ry_ratio: float = 0.45,
    horizon_half_width: float | None = None,
) -> None:
    """Draw the arc centred at (cx, cy) with radius r; cy is the horizon line."""
    layer = c.layer()
    d = ImageDraw.Draw(layer)

    half = horizon_half_width if horizon_half_width is not None else r * 1.18
    d.line(
        [(c.px(cx - half), c.px(cy)), (c.px(cx + half), c.px(cy))],
        fill=_alpha(WHITE, 0.28),
        width=c.px(max(1.5, stroke * 0.45)),
    )

    # Day arc: 180° (sunrise, left) -> 360° (sunset, right); elapsed part solid.
    elapsed_end = 180 + 180 * info.progress
    if info.progress > 0:
        d.arc(
            c.box(cx - r, cy - r, cx + r, cy + r),
            180,
            elapsed_end,
            fill=_alpha(SUN_RGB, 0.95),
            width=c.px(stroke),
        )
    if info.progress < 1:
        _dashed_arc(
            c,
            d,
            cx,
            cy,
            r,
            r,
            elapsed_end,
            360,
            stroke * 0.8,
            _alpha(WHITE, 0.45),
            dash=stroke * 2.2,
        )

    # Night arc below the horizon (flattened), 0° (sunset) -> 180° (sunrise).
    ry = r * night_ry_ratio
    if not info.is_day:
        night_end = 180 * info.night_progress
        if night_end > 0:
            d.arc(
                c.box(cx - r, cy - ry, cx + r, cy + ry),
                0,
                night_end,
                fill=_alpha(MOON_RGB, 0.8),
                width=c.px(stroke * 0.8),
            )
        _dashed_arc(
            c, d, cx, cy, r, ry, night_end, 180, stroke * 0.6, _alpha(WHITE, 0.3), dash=stroke * 2.2
        )
    else:
        _dashed_arc(
            c, d, cx, cy, r, ry, 0, 180, stroke * 0.5, _alpha(WHITE, 0.16), dash=stroke * 2.2
        )

    c.composite(layer)

    # Marker: glowing sun by day, moon by night.
    if info.is_day:
        x, y = _point(cx, cy, r, r, elapsed_end)
        glow = c.layer()
        ImageDraw.Draw(glow).ellipse(
            c.box(
                x - sun_radius * 2.4,
                y - sun_radius * 2.4,
                x + sun_radius * 2.4,
                y + sun_radius * 2.4,
            ),
            fill=_alpha(SUN_RGB, 0.5),
        )
        c.composite(glow.filter(ImageFilter.GaussianBlur(c.px(sun_radius * 0.9))))
        c.draw.ellipse(
            c.box(x - sun_radius, y - sun_radius, x + sun_radius, y + sun_radius),
            fill=_alpha(SUN_RGB, 1),
            outline=_alpha(WHITE, 0.9),
            width=c.px(max(1.5, sun_radius * 0.18)),
        )
    else:
        x, y = _point(cx, cy, r, ry, 180 * info.night_progress)
        rr = sun_radius * 0.85
        glow = c.layer()
        ImageDraw.Draw(glow).ellipse(
            c.box(x - rr * 2.2, y - rr * 2.2, x + rr * 2.2, y + rr * 2.2),
            fill=_alpha(MOON_RGB, 0.35),
        )
        c.composite(glow.filter(ImageFilter.GaussianBlur(c.px(rr * 0.9))))
        c.draw.ellipse(c.box(x - rr, y - rr, x + rr, y + rr), fill=_alpha(MOON_RGB, 1))
        c.draw.ellipse(
            c.box(x - rr * 0.35, y - rr * 1.25, x + rr * 1.1, y + rr * 0.2),
            fill=_alpha((40, 46, 90), 1),
        )
