"""Per-user saved locations ("speed dial").

State lives in PTB's ``user_data`` dict so it is persisted automatically::

    user_data["locations"] = [{"name": ..., "lat": ..., "lon": ..., "alias": ...}, ...]
    user_data["default_location"] = <index into that list>

Slots are shown to people 1-based (``/weather 2``); internally they are 0-based indexes.
"""

from __future__ import annotations

import unicodedata
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from weather_bot.geocode import Place

KEY_LOCATIONS = "locations"
KEY_DEFAULT = "default_location"
LEGACY_KEY = "location"  # single-location format from the first release

MAX_LOCATIONS = 10
MAX_ALIAS_LENGTH = 30
SAME_SPOT_DEGREES = 0.005  # ~500 m; closer than that counts as the same place

UserData = MutableMapping[str, Any]


@dataclass(frozen=True)
class SavedLocation:
    index: int
    place: Place
    alias: str | None
    is_default: bool

    @property
    def slot(self) -> int:
        return self.index + 1

    @property
    def label(self) -> str:
        return self.alias or self.place.name

    @property
    def card_name(self) -> str:
        """Name shown on the infographic: alias plus the real place when both exist."""
        if self.alias and self.alias.lower() != self.place.name.lower():
            return f"{self.alias} · {self.place.name}"
        return self.place.name


def normalize_alias(text: str | None) -> str | None:
    """NFKC-normalise, drop control/format characters, collapse spaces, cap the length."""
    cleaned = "".join(
        " " if ch.isspace() else ch
        for ch in unicodedata.normalize("NFKC", text or "")
        if not unicodedata.category(ch).startswith("C") or ch.isspace()
    )
    return " ".join(cleaned.split())[:MAX_ALIAS_LENGTH].strip() or None


def _migrate(user_data: UserData) -> None:
    legacy = user_data.pop(LEGACY_KEY, None)
    if legacy and KEY_LOCATIONS not in user_data:
        user_data[KEY_LOCATIONS] = [
            {"name": legacy["name"], "lat": legacy["lat"], "lon": legacy["lon"], "alias": None}
        ]
        user_data[KEY_DEFAULT] = 0


def _raw(user_data: UserData) -> list[dict[str, Any]]:
    _migrate(user_data)
    return user_data.setdefault(KEY_LOCATIONS, [])


def _to_saved(index: int, raw: dict[str, Any], default_index: int) -> SavedLocation:
    return SavedLocation(
        index=index,
        place=Place(name=raw["name"], latitude=raw["lat"], longitude=raw["lon"]),
        alias=raw.get("alias") or None,
        is_default=index == default_index,
    )


def list_locations(user_data: UserData) -> list[SavedLocation]:
    raw = _raw(user_data)
    default_index = user_data.get(KEY_DEFAULT, 0) if raw else -1
    return [_to_saved(i, item, default_index) for i, item in enumerate(raw)]


def get_default(user_data: UserData) -> SavedLocation | None:
    locations = list_locations(user_data)
    if not locations:
        return None
    index = user_data.get(KEY_DEFAULT, 0)
    if not 0 <= index < len(locations):
        index = 0
        user_data[KEY_DEFAULT] = 0
    return locations[index]


def add_location(
    user_data: UserData, place: Place, alias: str | None = None
) -> tuple[SavedLocation, bool]:
    """Add a place; returns (location, created). Re-sharing a known spot updates its alias."""
    raw = _raw(user_data)
    alias = normalize_alias(alias)
    for i, item in enumerate(raw):
        if (
            abs(item["lat"] - place.latitude) < SAME_SPOT_DEGREES
            and abs(item["lon"] - place.longitude) < SAME_SPOT_DEGREES
        ):
            if alias:
                item["alias"] = alias
            return list_locations(user_data)[i], False
    if len(raw) >= MAX_LOCATIONS:
        raise ValueError(f"You can save up to {MAX_LOCATIONS} locations. Remove one first.")
    raw.append({"name": place.name, "lat": place.latitude, "lon": place.longitude, "alias": alias})
    if len(raw) == 1:
        user_data[KEY_DEFAULT] = 0
    return list_locations(user_data)[-1], True


def set_default(user_data: UserData, index: int) -> SavedLocation | None:
    raw = _raw(user_data)
    if not 0 <= index < len(raw):
        return None
    user_data[KEY_DEFAULT] = index
    return list_locations(user_data)[index]


def remove_location(user_data: UserData, index: int) -> SavedLocation | None:
    raw = _raw(user_data)
    if not 0 <= index < len(raw):
        return None
    removed = list_locations(user_data)[index]
    raw.pop(index)
    default = user_data.get(KEY_DEFAULT, 0)
    if default == index:
        user_data[KEY_DEFAULT] = 0
    elif default > index:
        user_data[KEY_DEFAULT] = default - 1
    return removed


def rename_location(user_data: UserData, index: int, alias: str) -> SavedLocation | None:
    raw = _raw(user_data)
    if not 0 <= index < len(raw):
        return None
    raw[index]["alias"] = normalize_alias(alias)
    return list_locations(user_data)[index]


def resolve(user_data: UserData, query: str | None) -> SavedLocation | None:
    """Pick a saved location: empty -> default, digits -> slot number, text -> alias/name."""
    query = (query or "").strip()
    if not query:
        return get_default(user_data)
    locations = list_locations(user_data)
    if query.isdigit():
        slot = int(query)
        return locations[slot - 1] if 1 <= slot <= len(locations) else None
    q = query.lower()
    for loc in locations:  # exact alias or name first
        if q in {(loc.alias or "").lower(), loc.place.name.lower()}:
            return loc
    for loc in locations:  # then prefix / substring
        if (loc.alias or "").lower().startswith(q) or q in loc.place.name.lower():
            return loc
    return None
