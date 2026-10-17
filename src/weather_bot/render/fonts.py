"""Font loading with caching. Inter is bundled; DejaVu Sans is the fallback."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import ImageFont

log = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

Weight = Literal["regular", "medium", "semibold", "bold", "display"]

FILES: dict[Weight, str] = {
    "regular": "Inter-Regular.otf",
    "medium": "Inter-Medium.otf",
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "display": "InterDisplay-Bold.otf",
}

FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@lru_cache(maxsize=64)
def font(weight: Weight, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_DIR / FILES[weight]
    if path.exists():
        return ImageFont.truetype(str(path), size)
    for candidate in FALLBACKS:
        if Path(candidate).exists():
            log.warning("Bundled font %s missing, using %s", path.name, candidate)
            return ImageFont.truetype(candidate, size)
    log.error("No TrueType fonts found, falling back to Pillow's bitmap font")
    return ImageFont.load_default(size)
