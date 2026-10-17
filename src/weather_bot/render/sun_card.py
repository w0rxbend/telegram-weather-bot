"""The sun card: sunrise, sunset, daylight and a 7-day sunrise/sunset strip."""

from __future__ import annotations

import io
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from weather_bot.render.card import (
    INNER,
    PAD,
    SCALE,
    WIDTH,
    Canvas,
    _alpha,
    _header,
    _section_title,
)
from weather_bot.render.sunpath import SUN_RGB, draw_sun_path
from weather_bot.render.theme import RGB, WHITE
from weather_bot.sun import SunInfo, daylight_of, fmt_change, fmt_duration, sun_info
from weather_bot.weather import Forecast

HEIGHT = 1440

TOP: RGB = (28, 24, 74)
BOTTOM: RGB = (226, 122, 70)
WARM: RGB = (255, 168, 82)
VIOLET: RGB = (150, 110, 220)
GOLD: RGB = (255, 150, 60)


def _hero(c: Canvas, info: SunInfo, now: datetime) -> None:
    cx, cy, r = WIDTH / 2, 560, 300
    draw_sun_path(
        c,
        info,
        cx,
        cy,
        r,
        stroke=6,
        sun_radius=20,
        night_ry_ratio=0.36,
        horizon_half_width=INNER / 2,
    )

    # golden hours as warm overlays on the day arc
    if info.daylight > timedelta(0):
        share = min(0.5, 3600 / info.daylight.total_seconds()) * 180
        layer = c.layer()
        d = ImageDraw.Draw(layer)
        bbox = c.box(cx - r, cy - r, cx + r, cy + r)
        d.arc(bbox, 180, 180 + share, fill=_alpha(GOLD, 0.55), width=c.px(6))
        d.arc(bbox, 360 - share, 360, fill=_alpha(GOLD, 0.55), width=c.px(6))
        c.composite(layer)

    # sunrise / sunset labels under the horizon ends
    c.text(PAD, cy + 26, "SUNRISE", "medium", 18, alpha=0.62, tracking=1.6)
    c.text(PAD, cy + 94, info.sunrise.strftime("%H:%M"), "display", 54, anchor="ls")
    c.text(WIDTH - PAD, cy + 26, "SUNSET", "medium", 18, alpha=0.62, tracking=1.6, anchor="ra")
    c.text(WIDTH - PAD, cy + 94, info.sunset.strftime("%H:%M"), "display", 54, anchor="rs")

    # apex: solar noon
    c.text(
        cx,
        cy - r - 34,
        f"solar noon {info.solar_noon.strftime('%H:%M')}",
        "regular",
        20,
        alpha=0.6,
        anchor="ms",
    )

    # now marker label
    label = f"now {now.strftime('%H:%M')}"
    if info.is_day:
        import math

        a = math.radians(180 + 180 * info.progress)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        c.text(x, y - 36, label, "semibold", 22, anchor="ms")
    else:
        import math

        a = math.radians(180 * info.night_progress)
        x, y = cx + r * math.cos(a), cy + r * 0.36 * math.sin(a)
        c.text(x, y + 24, label, "semibold", 20, anchor="ma")


def _tiles(c: Canvas, info: SunInfo, fc: Forecast) -> None:
    tomorrow = fc.tomorrow
    next_sunrise = tomorrow.sunrise.strftime("%H:%M") if tomorrow else "—"
    night = timedelta(hours=24) - info.daylight
    gm0, gm1 = info.golden_morning
    ge0, ge1 = info.golden_evening
    next_label = "SUNSET IN" if info.next_event == "sunset" else "SUNRISE IN"
    next_at = (
        info.sunset
        if info.next_event == "sunset"
        else (
            info.sunrise
            if fc.local_now() < info.sunrise
            else (tomorrow.sunrise if tomorrow else info.sunrise)
        )
    )
    tiles = [
        ("DAYLIGHT", fmt_duration(info.daylight), fmt_change(info.change_vs_yesterday)),
        ("SOLAR NOON", info.solar_noon.strftime("%H:%M"), "sun at its highest"),
        (next_label, fmt_duration(info.time_to_next_event), f"at {next_at.strftime('%H:%M')}"),
        (
            "GOLDEN HOUR · AM",
            f"{gm0.strftime('%H:%M')}–{gm1.strftime('%H:%M')}",
            "soft morning light",
        ),
        (
            "GOLDEN HOUR · PM",
            f"{ge0.strftime('%H:%M')}–{ge1.strftime('%H:%M')}",
            "best sunset light",
        ),
        ("NIGHT", fmt_duration(night), f"sunrise tomorrow {next_sunrise}"),
    ]
    cols, gap, th, top = 3, 16, 128, 728
    tw = (INNER - gap * (cols - 1)) / cols
    for i, (label, value, sub) in enumerate(tiles):
        col, row = i % cols, i // cols
        x0 = PAD + col * (tw + gap)
        y0 = top + row * (th + gap)
        c.glass(x0, y0, x0 + tw, y0 + th)
        c.text(x0 + 22, y0 + 20, label, "medium", 18, alpha=0.62, tracking=1.6)
        size = 40 if len(value) <= 8 else 32
        c.text(x0 + 22, y0 + 84, value, "bold", size, anchor="ls")
        c.text(x0 + 22, y0 + 110, sub, "regular", 19, alpha=0.62, anchor="ls")


def _week(c: Canvas, fc: Forecast) -> None:
    days = fc.daily[:7]
    _section_title(c, 1030, "SUNRISE & SUNSET · NEXT 7 DAYS")
    x0, x1 = PAD + 110, WIDTH - PAD
    axis_y = 1072
    for hour in range(0, 25, 6):
        x = x0 + (x1 - x0) * hour / 24
        c.text(x, axis_y, f"{hour}h", "regular", 17, alpha=0.45, anchor="ma")
        c.draw.line(
            [(c.px(x), c.px(axis_y + 24)), (c.px(x), c.px(axis_y + 24 + 7 * 36))],
            fill=_alpha(WHITE, 0.10),
            width=c.px(1),
        )

    top, row_h = axis_y + 36, 36
    for i, day in enumerate(days):
        y = top + i * row_h
        name = "Today" if i == 0 else day.date.strftime("%a")
        c.text(PAD, y + 11, name, "medium", 21, alpha=0.9 if i == 0 else 0.7, anchor="lm")
        bar_y0, bar_y1 = y + 2, y + 20

        def hx(t: datetime) -> float:
            return x0 + (x1 - x0) * (t.hour * 60 + t.minute) / 1440

        layer = c.layer()
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle(
            c.box(x0, bar_y0 + 7, x1, bar_y1 - 7), radius=c.px(2), fill=_alpha(WHITE, 0.10)
        )
        c.composite(layer)
        if daylight_of(day) > timedelta(0):
            bx0, bx1 = hx(day.sunrise), hx(day.sunset)
            w, h = c.px(bx1 - bx0), c.px(bar_y1 - bar_y0)
            if w > 2:
                grad = Image.composite(
                    Image.new("RGB", (w, h), GOLD),
                    Image.new("RGB", (w, h), SUN_RGB),
                    Image.linear_gradient("L").rotate(90, expand=True).resize((w, h)),
                ).convert("RGBA")
                mask = Image.new("L", (w, h), 0)
                ImageDraw.Draw(mask).rounded_rectangle(
                    [0, 0, w - 1, h - 1], radius=c.px(9), fill=255
                )
                opacity = 0.95 if i == 0 else 0.8
                grad.putalpha(mask.point(lambda v, o=opacity: int(v * o)))
                c.composite(grad, bx0, bar_y0)
            c.text(
                bx0 + 10,
                y + 11,
                day.sunrise.strftime("%H:%M"),
                "semibold",
                16,
                rgb=(40, 30, 20),
                anchor="lm",
            )
            c.text(
                bx1 - 10,
                y + 11,
                day.sunset.strftime("%H:%M"),
                "semibold",
                16,
                rgb=(40, 30, 20),
                anchor="rm",
            )


def _footer(c: Canvas, fc: Forecast) -> None:
    c.text(PAD, HEIGHT - 30, "Sun times by Open-Meteo.com", "regular", 19, alpha=0.45, anchor="lm")
    c.text(
        WIDTH - PAD,
        HEIGHT - 30,
        f"Updated {fc.observed_at.strftime('%H:%M')} · {fc.timezone}",
        "regular",
        19,
        alpha=0.45,
        anchor="rm",
    )


def render_sun_image(fc: Forecast, place_name: str, now: datetime | None = None) -> Image.Image:
    now = now or fc.local_now()
    info = sun_info(fc, now)

    c = Canvas(WIDTH, HEIGHT, SCALE)
    c.background(TOP, BOTTOM)
    c.glow(WIDTH / 2, 600, 420, WARM, 0.38, 120)
    c.glow(80, 120, 320, VIOLET, 0.28, 110)
    c.glow(WIDTH - 40, 1250, 300, WARM, 0.16, 100)

    _header(c, fc, place_name, now)
    note = f"{info.next_event} in {fmt_duration(info.time_to_next_event)}"
    _section_title(c, 190, "SUN TODAY", note)
    _hero(c, info, now)
    _tiles(c, info, fc)
    _week(c, fc)
    _footer(c, fc)
    return c.finish()


def render_sun_card(fc: Forecast, place_name: str, now: datetime | None = None) -> bytes:
    buf = io.BytesIO()
    render_sun_image(fc, place_name, now).save(buf, format="PNG", optimize=True)
    return buf.getvalue()
