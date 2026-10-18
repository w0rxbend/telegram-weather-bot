"""Procedurally drawn weather icons.

Every icon is drawn into a 100x100 design box, supersampled 4x and downscaled with
Lanczos so the edges are smooth. Nothing here depends on external image assets.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from weather_bot.weather import IconKind

RGBA = tuple[int, int, int, int]

SUN: RGBA = (255, 204, 77, 255)
SUN_GLOW: RGBA = (255, 190, 60, 120)
MOON: RGBA = (236, 240, 252, 255)
MOON_GLOW: RGBA = (200, 210, 255, 90)
CLOUD: RGBA = (255, 255, 255, 255)
CLOUD_SHADE: RGBA = (205, 215, 235, 255)
CLOUD_DARK: RGBA = (196, 206, 226, 255)
CLOUD_DARK_SHADE: RGBA = (150, 162, 190, 255)
STORM: RGBA = (160, 168, 196, 255)
STORM_SHADE: RGBA = (112, 120, 150, 255)
RAIN: RGBA = (125, 195, 255, 255)
SNOW: RGBA = (255, 255, 255, 255)
BOLT: RGBA = (255, 214, 64, 255)
FOG: RGBA = (255, 255, 255, 215)

SS = 4  # supersampling factor


class _Pen:
    """Tiny helper that draws in a 100-unit design box scaled to the real canvas."""

    def __init__(self, size: int) -> None:
        self.size = size * SS
        self.u = self.size / 100.0
        self.img = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        self.glow = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def p(self, v: float) -> float:
        return v * self.u

    def circle(self, cx: float, cy: float, r: float, fill: RGBA) -> None:
        self.d.ellipse([self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)], fill=fill)

    def stroke(self, x1: float, y1: float, x2: float, y2: float, w: float, fill: RGBA) -> None:
        self.d.line(
            [(self.p(x1), self.p(y1)), (self.p(x2), self.p(y2))], fill=fill, width=int(self.p(w))
        )
        self.circle(x1, y1, w / 2, fill)
        self.circle(x2, y2, w / 2, fill)

    def soft_glow(self, cx: float, cy: float, r: float, fill: RGBA, blur: float) -> None:
        g = ImageDraw.Draw(self.glow)
        g.ellipse([self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)], fill=fill)
        self.glow = self.glow.filter(ImageFilter.GaussianBlur(self.p(blur)))

    # -- composite shapes ---------------------------------------------------------------

    def sun(self, cx: float, cy: float, r: float) -> None:
        self.soft_glow(cx, cy, r * 1.9, SUN_GLOW, r * 0.45)
        for i in range(8):
            a = math.radians(i * 45)
            x1, y1 = cx + math.cos(a) * r * 1.42, cy + math.sin(a) * r * 1.42
            x2, y2 = cx + math.cos(a) * r * 1.82, cy + math.sin(a) * r * 1.82
            self.stroke(x1, y1, x2, y2, r * 0.24, SUN)
        self.circle(cx, cy, r, SUN)

    def moon(self, cx: float, cy: float, r: float) -> None:
        self.soft_glow(cx, cy, r * 1.7, MOON_GLOW, r * 0.5)
        mask = Image.new("L", (self.size, self.size), 0)
        m = ImageDraw.Draw(mask)
        m.ellipse([self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)], fill=255)
        ox, oy, orad = cx + r * 0.55, cy - r * 0.35, r * 0.82
        m.ellipse(
            [self.p(ox - orad), self.p(oy - orad), self.p(ox + orad), self.p(oy + orad)], fill=0
        )
        self.img.paste(MOON, (0, 0), mask)
        self.d = ImageDraw.Draw(self.img)

    def cloud(self, cx: float, cy: float, w: float, fill: RGBA, shade: RGBA) -> None:
        h = w * 0.62
        # shaded copy slightly offset gives the cloud some depth
        self._cloud_shape(cx + w * 0.03, cy + h * 0.08, w, shade)
        self._cloud_shape(cx, cy, w, fill)

    def _cloud_shape(self, cx: float, cy: float, w: float, fill: RGBA) -> None:
        h = w * 0.62
        self.d.rounded_rectangle(
            [self.p(cx - w / 2), self.p(cy - h * 0.02), self.p(cx + w / 2), self.p(cy + h * 0.45)],
            radius=self.p(h * 0.24),
            fill=fill,
        )
        self.circle(cx - w * 0.12, cy - h * 0.14, w * 0.30, fill)
        self.circle(cx + w * 0.22, cy + h * 0.02, w * 0.225, fill)
        self.circle(cx - w * 0.34, cy + h * 0.12, w * 0.19, fill)

    def drops(self, cx: float, y: float, spread: float, count: int, length: float) -> None:
        for i in range(count):
            t = (i - (count - 1) / 2) / max(count - 1, 1)
            x = cx + t * spread
            offset = abs(t) * length * 0.35
            self.stroke(x, y + offset, x - length * 0.32, y + offset + length, 4.2, RAIN)

    def flakes(self, cx: float, y: float, spread: float, count: int, r: float) -> None:
        for i in range(count):
            t = (i - (count - 1) / 2) / max(count - 1, 1)
            x = cx + t * spread
            yy = y + abs(t) * r * 1.2
            for k in range(3):
                a = math.radians(k * 60)
                self.stroke(
                    x - math.cos(a) * r,
                    yy - math.sin(a) * r,
                    x + math.cos(a) * r,
                    yy + math.sin(a) * r,
                    2.6,
                    SNOW,
                )

    def bolt(self, cx: float, cy: float, s: float) -> None:
        pts = [
            (0.10, 0.0),
            (-0.34, 0.56),
            (-0.04, 0.56),
            (-0.26, 1.0),
            (0.40, 0.38),
            (0.08, 0.38),
            (0.30, 0.0),
        ]
        self.d.polygon([(self.p(cx + x * s), self.p(cy + y * s)) for x, y in pts], fill=BOLT)

    def fog_lines(self, cx: float, y: float, w: float) -> None:
        for i, (shift, frac) in enumerate(((0.0, 1.0), (-0.08, 0.72), (0.06, 0.86))):
            yy = y + i * 9.5
            half = w * frac / 2
            self.stroke(cx + shift * w - half, yy, cx + shift * w + half, yy, 4.6, FOG)

    def render(self, size: int) -> Image.Image:
        out = Image.alpha_composite(self.glow, self.img)
        return out.resize((size, size), Image.Resampling.LANCZOS)


def _draw(pen: _Pen, kind: IconKind, is_day: bool) -> None:
    sky = pen.sun if is_day else pen.moon
    if kind == "clear":
        sky(50, 50, 24)
    elif kind == "mostly-clear":
        sky(46, 44, 23)
        pen.cloud(66, 70, 36, CLOUD, CLOUD_SHADE)
    elif kind == "partly-cloudy":
        sky(38, 38, 19)
        pen.cloud(58, 60, 56, CLOUD, CLOUD_SHADE)
    elif kind == "overcast":
        pen.cloud(60, 36, 46, CLOUD_DARK, CLOUD_DARK_SHADE)
        pen.cloud(44, 58, 62, CLOUD, CLOUD_SHADE)
    elif kind == "fog":
        pen.cloud(50, 40, 56, CLOUD_DARK, CLOUD_DARK_SHADE)
        pen.fog_lines(50, 64, 54)
    elif kind == "drizzle":
        pen.cloud(50, 40, 58, CLOUD, CLOUD_SHADE)
        pen.drops(50, 64, 30, 3, 9)
    elif kind == "rain":
        pen.cloud(50, 38, 60, CLOUD_DARK, CLOUD_DARK_SHADE)
        pen.drops(50, 62, 34, 3, 16)
    elif kind == "heavy-rain":
        pen.cloud(50, 36, 62, STORM, STORM_SHADE)
        pen.drops(50, 60, 40, 4, 20)
    elif kind == "snow":
        pen.cloud(50, 38, 60, CLOUD, CLOUD_SHADE)
        pen.flakes(50, 70, 34, 3, 5.5)
    elif kind == "showers":
        sky(36, 34, 17)
        pen.cloud(56, 50, 54, CLOUD, CLOUD_SHADE)
        pen.drops(56, 72, 30, 3, 13)
    elif kind == "snow-showers":
        sky(36, 34, 17)
        pen.cloud(56, 50, 54, CLOUD, CLOUD_SHADE)
        pen.flakes(56, 78, 30, 3, 5)
    else:  # "thunder", the last member of IconKind
        pen.cloud(50, 36, 62, STORM, STORM_SHADE)
        pen.drops(30, 62, 10, 2, 13)
        pen.drops(72, 62, 10, 2, 13)
        pen.bolt(50, 54, 36)


@lru_cache(maxsize=128)
def icon(kind: IconKind, is_day: bool, size: int) -> Image.Image:
    pen = _Pen(size)
    _draw(pen, kind, is_day)
    return pen.render(size)
