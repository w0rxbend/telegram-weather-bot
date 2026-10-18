"""Compose the weather infographic.

Layout is described in logical pixels on a 1080x1500 canvas, drawn at ``SCALE``x and
downsampled with Lanczos so every edge and glyph is antialiased.
"""

from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from weather_bot.render import icons
from weather_bot.render.fonts import Weight, font
from weather_bot.render.theme import (
    RAIN_BLUE,
    RGB,
    WHITE,
    pressure_label,
    temp_colour,
    theme_for,
    uv_label,
)
from weather_bot.weather import DayPoint, Forecast, HourPoint, compass, describe, icon_kind
import itertools

WIDTH, HEIGHT = 1080, 1600
SCALE = 2
PAD = 64
INNER = WIDTH - 2 * PAD


def _alpha(rgb: RGB, a: float) -> tuple[int, int, int, int]:
    return (*rgb, round(255 * a))


class Canvas:
    def __init__(self, width: int, height: int, scale: int) -> None:
        self.scale = scale
        self.w, self.h = width * scale, height * scale
        self.img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 255))
        self.draw = ImageDraw.Draw(self.img)

    # -- geometry -----------------------------------------------------------------------

    def px(self, v: float) -> int:
        return round(v * self.scale)

    def box(self, x0: float, y0: float, x1: float, y1: float) -> list[int]:
        return [self.px(x0), self.px(y0), self.px(x1), self.px(y1)]

    # -- layers -------------------------------------------------------------------------

    def composite(self, layer: Image.Image, x: float = 0, y: float = 0) -> None:
        self.img.alpha_composite(layer, (self.px(x), self.px(y)))
        self.draw = ImageDraw.Draw(self.img)

    def layer(self) -> Image.Image:
        return Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))

    def background(self, top: RGB, bottom: RGB) -> None:
        mask = Image.linear_gradient("L").resize((self.w, self.h))
        grad = Image.composite(
            Image.new("RGB", (self.w, self.h), bottom),
            Image.new("RGB", (self.w, self.h), top),
            mask,
        )
        self.img.paste(grad, (0, 0))
        self.draw = ImageDraw.Draw(self.img)

    def glow(self, cx: float, cy: float, r: float, rgb: RGB, alpha: float, blur: float) -> None:
        layer = self.layer()
        ImageDraw.Draw(layer).ellipse(
            self.box(cx - r, cy - r, cx + r, cy + r), fill=_alpha(rgb, alpha)
        )
        layer = layer.filter(ImageFilter.GaussianBlur(self.px(blur)))
        self.composite(layer)

    def glass(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float = 28,
        fill: float = 0.11,
        outline: float = 0.22,
    ) -> None:
        layer = self.layer()
        ImageDraw.Draw(layer).rounded_rectangle(
            self.box(x0, y0, x1, y1),
            radius=self.px(radius),
            fill=_alpha(WHITE, fill),
            outline=_alpha(WHITE, outline),
            width=self.px(1.5),
        )
        self.composite(layer)

    # -- text ---------------------------------------------------------------------------

    def text(
        self,
        x: float,
        y: float,
        s: str,
        weight: Weight = "regular",
        size: int = 24,
        rgb: RGB = WHITE,
        alpha: float = 1.0,
        anchor: str = "la",
        tracking: float = 0.0,
    ) -> float:
        """Draw text and return its advance width in logical pixels."""
        f = font(weight, self.px(size))
        fill = _alpha(rgb, alpha)
        if not tracking:
            self.draw.text((self.px(x), self.px(y)), s, font=f, fill=fill, anchor=anchor)
            return self.draw.textlength(s, font=f) / self.scale

        # Pillow has no letter-spacing, so lay the glyphs out by hand.
        widths = [self.draw.textlength(ch, font=f) / self.scale for ch in s]
        total = sum(widths) + tracking * (len(s) - 1)
        start = x
        if anchor[0] == "m":
            start = x - total / 2
        elif anchor[0] == "r":
            start = x - total
        cursor = start
        for ch, w in zip(s, widths, strict=True):
            self.draw.text(
                (self.px(cursor), self.px(y)), ch, font=f, fill=fill, anchor="l" + anchor[1]
            )
            cursor += w + tracking
        return total

    def text_width(self, s: str, weight: Weight, size: int) -> float:
        return self.draw.textlength(s, font=font(weight, self.px(size))) / self.scale

    # -- images -------------------------------------------------------------------------

    def icon(self, kind: str, is_day: bool, size: int, x: float, y: float) -> None:
        im = icons.icon(kind, is_day, self.px(size))  # type: ignore[arg-type]
        self.composite(im, x, y)

    def finish(self) -> Image.Image:
        return self.img.convert("RGB").resize(
            (self.w // self.scale, self.h // self.scale), Image.Resampling.LANCZOS
        )


# --- helpers ------------------------------------------------------------------------------


def _fmt_temp(value: float) -> str:
    return f"{round(value):d}°"


def _catmull_rom(points: list[tuple[float, float]], steps: int = 14) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    pts = [points[0], *points, points[-1]]
    out: list[tuple[float, float]] = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            x = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            out.append((x, y))
    out.append(points[-1])
    return out


def _day_name(day: DayPoint, index: int) -> str:
    return "Today" if index == 0 else day.date.strftime("%a")


def _hour_label(point: HourPoint, index: int) -> str:
    return "Now" if index == 0 else point.time.strftime("%H:%M")


# --- sections -----------------------------------------------------------------------------


def _header(c: Canvas, fc: Forecast, place_name: str, now: datetime) -> None:
    name = place_name
    while c.text_width(name, "semibold", 46) > INNER - 200 and len(name) > 4:
        name = name[:-2].rstrip(" ,") + "…"
    c.text(PAD, 70, name, "semibold", 46)
    c.text(PAD, 130, now.strftime("%A, %d %B · %H:%M"), "regular", 27, alpha=0.72)

    pill = f"{fc.latitude:.2f}, {fc.longitude:.2f}"
    w = c.text_width(pill, "medium", 22) + 36
    c.glass(WIDTH - PAD - w, 72, WIDTH - PAD, 118, radius=23, fill=0.12, outline=0.25)
    c.text(WIDTH - PAD - w / 2, 95, pill, "medium", 22, alpha=0.9, anchor="mm")


def _hero(c: Canvas, fc: Forecast) -> None:
    kind = icon_kind(fc.weather_code)
    temp = _fmt_temp(fc.temperature)
    c.text(PAD - 10, 140, temp, "display", 236, anchor="la")
    c.text(PAD, 410, describe(fc.weather_code), "semibold", 42)
    today = fc.today
    line = (
        f"Feels like {_fmt_temp(fc.apparent_temperature)}   ·   "
        f"H {_fmt_temp(today.t_max)}   L {_fmt_temp(today.t_min)}"
    )
    c.text(PAD, 468, line, "regular", 30, alpha=0.78)
    c.icon(kind, fc.is_day, 320, WIDTH - PAD - 320, 165)


def _stats(c: Canvas, fc: Forecast, now: datetime) -> None:
    today = fc.today
    tiles = [
        (
            "WIND",
            f"{fc.wind_speed:.0f}",
            fc.speed_unit,
            f"{compass(fc.wind_direction)} · gusts {fc.wind_gusts:.0f}",
        ),
        ("HUMIDITY", f"{fc.humidity}", "%", f"Cloud cover {fc.cloud_cover}%"),
        ("UV INDEX", f"{today.uv_index_max:.0f}", "", uv_label(today.uv_index_max)),
        (
            "RAIN CHANCE",
            f"{today.precipitation_probability_max}",
            "%",
            f"{today.precipitation_sum:.1f} {fc.precip_unit} today",
        ),
        ("PRESSURE", f"{fc.pressure:.0f}", "hPa", pressure_label(fc.pressure)),
    ]
    cols = 3
    gap = 16
    tw = (INNER - gap * (cols - 1)) / cols
    th = 128
    top = 540
    for i, (label, value, unit, sub) in enumerate(tiles):
        col, row = i % cols, i // cols
        x0 = PAD + col * (tw + gap)
        y0 = top + row * (th + gap)
        c.glass(x0, y0, x0 + tw, y0 + th)
        c.text(x0 + 22, y0 + 20, label, "medium", 18, alpha=0.62, tracking=1.6)
        adv = c.text(x0 + 22, y0 + 84, value, "bold", 40, anchor="ls")
        if unit:
            c.text(x0 + 22 + adv + 6, y0 + 84, unit, "medium", 20, alpha=0.75, anchor="ls")
        c.text(x0 + 22, y0 + 110, sub, "regular", 19, alpha=0.62, anchor="ls")

    # sixth tile: sun path
    x0 = PAD + 2 * (tw + gap)
    y0 = top + th + gap
    _sun_tile(c, fc, now, x0, y0, tw, th)


def _sun_tile(
    c: Canvas, fc: Forecast, now: datetime, x0: float, y0: float, tw: float, th: float
) -> None:
    from weather_bot.render.sunpath import draw_sun_path
    from weather_bot.sun import fmt_duration, sun_info

    info = sun_info(fc, now)
    c.glass(x0, y0, x0 + tw, y0 + th)
    c.text(x0 + 22, y0 + 20, "SUN", "medium", 18, alpha=0.62, tracking=1.6)
    c.text(
        x0 + tw - 22, y0 + 20, fmt_duration(info.daylight), "medium", 18, alpha=0.62, anchor="ra"
    )
    horizon = y0 + th - 30
    draw_sun_path(
        c,
        info,
        x0 + tw / 2,
        horizon,
        58,
        stroke=3,
        sun_radius=7,
        night_ry_ratio=0.3,
        horizon_half_width=tw / 2 - 22,
    )
    c.text(
        x0 + 22, horizon + 20, f"↑ {info.sunrise.strftime('%H:%M')}", "semibold", 18, anchor="ls"
    )
    c.text(
        x0 + tw - 22,
        horizon + 20,
        f"↓ {info.sunset.strftime('%H:%M')}",
        "semibold",
        18,
        anchor="rs",
    )


def _section_title(c: Canvas, y: float, title: str, note: str | None = None) -> None:
    c.text(PAD, y, title, "medium", 20, alpha=0.62, tracking=2.2)
    if note:
        c.text(WIDTH - PAD, y, note, "regular", 20, alpha=0.5, anchor="ra")


def _hourly(c: Canvas, fc: Forecast) -> None:
    points = fc.next_hours(24)
    if len(points) < 2:
        return
    _section_title(c, 846, "NEXT 24 HOURS", "bars = chance of rain")

    icon_y = 892
    chart_top, chart_bottom = 1000, 1090
    bars_top, bars_bottom = 1106, 1140
    label_y = 1164
    x0, x1 = PAD + 16, WIDTH - PAD - 16
    n = len(points)
    step = (x1 - x0) / (n - 1)

    temps = [p.temperature for p in points]
    lo, hi = min(temps), max(temps)
    if hi - lo < 4:
        mid = (hi + lo) / 2
        lo, hi = mid - 2, mid + 2

    def ty(t: float) -> float:
        return chart_bottom - (t - lo) / (hi - lo) * (chart_bottom - chart_top)

    xs = [x0 + i * step for i in range(n)]
    raw = [(x, ty(t)) for x, t in zip(xs, temps, strict=True)]
    curve = _catmull_rom(raw)

    # soft white area under the curve, fading downwards
    imperial = fc.units == "imperial"
    base_y = bars_top - 6
    mask = Image.new("L", (c.w, c.h), 0)
    poly = [(c.px(x), c.px(y)) for x, y in curve]
    poly += [(c.px(curve[-1][0]), c.px(base_y)), (c.px(curve[0][0]), c.px(base_y))]
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    fade = Image.linear_gradient("L").resize((c.w, c.px(base_y - chart_top + 40)))
    fade = ImageChops.invert(fade)
    fade_full = Image.new("L", (c.w, c.h), 0)
    fade_full.paste(fade, (0, c.px(chart_top - 40)))
    mask = ImageChops.multiply(mask, fade_full)
    mask = mask.point(lambda v: int(v * 0.22))
    area = Image.new("RGBA", (c.w, c.h), (*WHITE, 0))
    area.putalpha(mask)
    c.composite(area)

    # line, coloured by the temperature at each point
    line_layer = c.layer()
    ld = ImageDraw.Draw(line_layer)
    lw = 4.5
    for (xa, ya), (xb, yb) in itertools.pairwise(curve):
        t = lo + (chart_bottom - (ya + yb) / 2) / (chart_bottom - chart_top) * (hi - lo)
        colour = _alpha(temp_colour(t, imperial), 1.0)
        ld.line([(c.px(xa), c.px(ya)), (c.px(xb), c.px(yb))], fill=colour, width=c.px(lw))
        ld.ellipse(c.box(xb - lw / 2, yb - lw / 2, xb + lw / 2, yb + lw / 2), fill=colour)
    c.composite(line_layer)

    # rain-probability bars under the chart
    bar_layer = c.layer()
    bd = ImageDraw.Draw(bar_layer)
    bw = step * 0.55
    for x, p in zip(xs, points, strict=True):
        h = max(2.0, (bars_bottom - bars_top) * p.precipitation_probability / 100)
        a = 0.18 + 0.72 * p.precipitation_probability / 100
        bd.rounded_rectangle(
            c.box(x - bw / 2, bars_bottom - h, x + bw / 2, bars_bottom),
            radius=c.px(3),
            fill=_alpha(RAIN_BLUE, a),
        )
    c.composite(bar_layer)

    # dots, labels and icons every three hours
    for i in range(0, n, 3):
        x, y = raw[i]
        p = points[i]
        colour = _alpha(temp_colour(p.temperature, imperial), 1.0)
        c.draw.ellipse(
            c.box(x - 7, y - 7, x + 7, y + 7), fill=_alpha(WHITE, 1), outline=colour, width=c.px(3)
        )
        c.text(x, y - 18, _fmt_temp(p.temperature), "semibold", 26, anchor="ms")
        c.icon(icon_kind(p.weather_code), p.is_day, 48, x - 24, icon_y)
        c.text(x, label_y, _hour_label(p, i), "regular", 22, alpha=0.7, anchor="ma")


def _daily(c: Canvas, fc: Forecast) -> None:
    days = fc.daily[:7]
    if not days:
        return
    _section_title(c, 1240, "7-DAY FORECAST")

    top = 1290
    col_w = INNER / len(days)
    week_lo = min(d.t_min for d in days)
    week_hi = max(d.t_max for d in days)
    if week_hi - week_lo < 1:
        week_hi = week_lo + 1
    bar_top, bar_bottom = top + 112, top + 182
    imperial = fc.units == "imperial"

    for i, day in enumerate(days):
        cx = PAD + col_w * (i + 0.5)
        if i == 0:
            c.glass(
                cx - col_w / 2 + 2,
                top - 12,
                cx + col_w / 2 - 2,
                bar_bottom + 70,
                radius=24,
                fill=0.08,
                outline=0.16,
            )
        c.text(cx, top, _day_name(day, i), "medium", 22, alpha=0.9 if i == 0 else 0.7, anchor="ma")
        c.icon(icon_kind(day.weather_code), True, 56, cx - 28, top + 32)
        c.text(cx, top + 103, _fmt_temp(day.t_max), "semibold", 26, anchor="ms")

        # vertical range bar: track for the whole week, filled segment for this day
        track = c.layer()
        td = ImageDraw.Draw(track)
        td.rounded_rectangle(
            c.box(cx - 5, bar_top, cx + 5, bar_bottom), radius=c.px(5), fill=_alpha(WHITE, 0.16)
        )
        c.composite(track)

        def y_of(t: float) -> float:
            return bar_bottom - (t - week_lo) / (week_hi - week_lo) * (bar_bottom - bar_top)

        y_hi, y_lo = y_of(day.t_max), y_of(day.t_min)
        if y_lo - y_hi < 10:
            y_lo = y_hi + 10
        seg_h = c.px(y_lo - y_hi)
        seg_w = c.px(10)
        grad = Image.composite(
            Image.new("RGB", (seg_w, seg_h), temp_colour(day.t_min, imperial)),
            Image.new("RGB", (seg_w, seg_h), temp_colour(day.t_max, imperial)),
            Image.linear_gradient("L").resize((seg_w, seg_h)),
        ).convert("RGBA")
        seg_mask = Image.new("L", (seg_w, seg_h), 0)
        ImageDraw.Draw(seg_mask).rounded_rectangle(
            [0, 0, seg_w - 1, seg_h - 1], radius=c.px(5), fill=255
        )
        grad.putalpha(seg_mask)
        c.composite(grad, cx - 5, y_hi)

        c.text(cx, bar_bottom + 18, _fmt_temp(day.t_min), "regular", 24, alpha=0.7, anchor="ma")
        if day.precipitation_probability_max >= 30:
            c.text(
                cx,
                bar_bottom + 50,
                f"{day.precipitation_probability_max}%",
                "medium",
                19,
                rgb=RAIN_BLUE,
                anchor="ma",
            )


def _footer(c: Canvas, fc: Forecast, now: datetime) -> None:
    c.text(
        PAD, HEIGHT - 30, "Weather data by Open-Meteo.com", "regular", 19, alpha=0.45, anchor="lm"
    )
    updated = f"Updated {fc.observed_at.strftime('%H:%M')} · {fc.timezone}"
    c.text(WIDTH - PAD, HEIGHT - 30, updated, "regular", 19, alpha=0.45, anchor="rm")


# --- public API ---------------------------------------------------------------------------


def render_image(fc: Forecast, place_name: str, now: datetime | None = None) -> Image.Image:
    now = now or fc.local_now()
    kind = icon_kind(fc.weather_code)
    theme = theme_for(kind, fc.is_day)

    c = Canvas(WIDTH, HEIGHT, SCALE)
    c.background(theme.top, theme.bottom)
    c.glow(WIDTH - 120, 260, 330, theme.glow_a, 0.30, 90)
    c.glow(60, 1150, 420, theme.glow_b, 0.22, 110)
    c.glow(WIDTH - 60, 1500, 280, theme.glow_a, 0.14, 90)

    _header(c, fc, place_name, now)
    _hero(c, fc)
    _stats(c, fc, now)
    _hourly(c, fc)
    _daily(c, fc)
    _footer(c, fc, now)
    return c.finish()


def render_card(fc: Forecast, place_name: str, now: datetime | None = None) -> bytes:
    """Render the infographic and return it as PNG bytes."""
    image = render_image(fc, place_name, now)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
