"""The usage card for the operator: totals plus ranked bar charts for users, cities, actions."""

from __future__ import annotations

import io
from datetime import datetime

from PIL import ImageDraw

from weather_bot.render.card import INNER, PAD, SCALE, WIDTH, Canvas, _alpha
from weather_bot.render.theme import RGB
from weather_bot.telemetry import Ranked, UsageReport

HEADER_HEIGHT = 392
TITLE_GAP = 46
SECTION_GAP = 46
FOOTER_HEIGHT = 70
BAR_ROWS = 8
ROW_PITCH = 48
BAR_HEIGHT = 34

TOP: RGB = (14, 22, 52)
BOTTOM: RGB = (44, 36, 98)
CITY_COLOUR: RGB = (96, 210, 255)
USER_COLOUR: RGB = (255, 190, 84)
ACTION_COLOUR: RGB = (170, 130, 255)


def _chart_height(rows: list[Ranked]) -> int:
    return TITLE_GAP + max(len(rows[:BAR_ROWS]), 1) * ROW_PITCH + SECTION_GAP


def _fit(c: Canvas, text: str, max_width: float) -> str:
    while c.text_width(text, "medium", 24) > max_width and len(text) > 4:
        text = text[:-2].rstrip(" ,") + "…"
    return text


def _kpi(c: Canvas, x: float, width: float, value: int, label: str) -> None:
    c.glass(x, 190, x + width, 330)
    c.text(x + width / 2, 262, f"{value:,}".replace(",", " "), "display", 58, anchor="mm")
    c.text(x + width / 2, 308, label, "medium", 18, alpha=0.62, tracking=1.8, anchor="mm")


def _bar_chart(c: Canvas, y: float, title: str, rows: list[Ranked], colour: RGB) -> float:
    """Draw one titled chart starting at ``y``; return the y below it."""
    c.text(PAD, y, title, "medium", 20, alpha=0.62, tracking=2.2)
    rows = rows[:BAR_ROWS]
    if not rows:
        c.text(PAD, y + TITLE_GAP + 10, "no data yet", "regular", 24, alpha=0.5)
        return y + _chart_height(rows)
    peak = max(row.count for row in rows)
    label_width = 400
    bar_x0 = PAD + label_width + 16
    bar_span = INNER - label_width - 16 - 90
    for index, row in enumerate(rows):
        top = y + TITLE_GAP + index * ROW_PITCH
        mid = top + BAR_HEIGHT / 2
        c.text(PAD, mid, _fit(c, row.label, label_width), "medium", 24, alpha=0.92, anchor="lm")
        c.glass(bar_x0, top, bar_x0 + bar_span, top + BAR_HEIGHT, radius=17, fill=0.07, outline=0)
        fill = max(BAR_HEIGHT, bar_span * row.count / peak)
        layer = c.layer()
        ImageDraw.Draw(layer).rounded_rectangle(
            c.box(bar_x0, top, bar_x0 + fill, top + BAR_HEIGHT),
            radius=c.px(17),
            fill=_alpha(colour, 0.85 - 0.5 * index / BAR_ROWS),
        )
        c.composite(layer)
        c.text(WIDTH - PAD, mid, str(row.count), "semibold", 24, anchor="rm")
    return y + _chart_height(rows)


def render_stats_card(report: UsageReport, now: datetime) -> bytes:
    charts = [
        ("TOP CITIES", report.top_cities, CITY_COLOUR),
        ("TOP USERS", report.top_users, USER_COLOUR),
        ("TOP ACTIONS", report.top_events, ACTION_COLOUR),
    ]
    height = HEADER_HEIGHT + sum(_chart_height(rows) for _, rows, _ in charts) + FOOTER_HEIGHT
    c = Canvas(WIDTH, height, SCALE)
    c.background(TOP, BOTTOM)
    c.glow(WIDTH - 100, 200, 340, CITY_COLOUR, 0.20, 100)
    c.glow(60, height * 0.75, 420, ACTION_COLOUR, 0.22, 110)

    c.text(PAD, 70, "Bot usage", "semibold", 46)
    c.text(PAD, 130, now.strftime("%A, %d %B · %H:%M"), "regular", 27, alpha=0.72)

    gap = 20
    tile = (INNER - 2 * gap) / 3
    _kpi(c, PAD, tile, report.users, "USERS")
    _kpi(c, PAD + tile + gap, tile, report.events, "ACTIONS")
    _kpi(c, PAD + 2 * (tile + gap), tile, report.cards, "CARDS")

    y = float(HEADER_HEIGHT)
    for title, rows, colour in charts:
        y = _bar_chart(c, y, title, rows, colour)

    c.text(PAD, height - 30, "Private: operator only", "regular", 19, alpha=0.45, anchor="lm")
    buf = io.BytesIO()
    c.finish().save(buf, format="PNG", optimize=True)
    return buf.getvalue()
