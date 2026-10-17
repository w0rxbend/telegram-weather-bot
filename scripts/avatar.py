"""Render a 512x512 bot avatar (upload it in @BotFather with /setuserpic).

Usage: python scripts/avatar.py [--out docs/avatar.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weather_bot.render import icons  # noqa: E402
from weather_bot.render.theme import theme_for  # noqa: E402


def render_avatar(size: int = 512) -> Image.Image:
    scale = 2
    s = size * scale
    theme = theme_for("partly-cloudy", True)
    mask = Image.linear_gradient("L").resize((s, s)).rotate(30, resample=Image.Resampling.BICUBIC)
    img = Image.composite(
        Image.new("RGB", (s, s), theme.bottom), Image.new("RGB", (s, s), theme.top), mask
    ).convert("RGBA")

    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([s * 0.15, s * 0.1, s * 0.85, s * 0.8], fill=(*theme.glow_a, 110))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.12)))

    icon = icons.icon("partly-cloudy", True, int(s * 0.78))
    img.alpha_composite(icon, (int(s * 0.11), int(s * 0.13)))
    return img.resize((size, size), Image.Resampling.LANCZOS).convert("RGB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("docs/avatar.png"))
    args = ap.parse_args()
    render_avatar().save(args.out, format="PNG", optimize=True)
    print(f"wrote {args.out}")
