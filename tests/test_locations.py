from __future__ import annotations

import pytest

from weather_bot import locations as store
from weather_bot.geocode import Place

KYIV = Place("Kyiv, Ukraine", 50.45, 30.52)
LVIV = Place("Lviv, Ukraine", 49.84, 24.03)
PARIS = Place("Paris, France", 48.85, 2.35)


def test_add_first_becomes_default() -> None:
    data: dict = {}
    loc, created = store.add_location(data, KYIV)
    assert created and loc.slot == 1 and loc.is_default
    assert store.get_default(data).place == KYIV


def test_add_more_keeps_default_and_resolves_by_slot_alias_name() -> None:
    data: dict = {}
    store.add_location(data, KYIV)
    store.add_location(data, LVIV, "home")
    store.add_location(data, PARIS, "Office")
    assert store.get_default(data).place == KYIV
    assert store.resolve(data, None).place == KYIV
    assert store.resolve(data, "2").place == LVIV
    assert store.resolve(data, "home").place == LVIV
    assert store.resolve(data, "OFF").place == PARIS  # alias prefix
    assert store.resolve(data, "paris").place == PARIS  # name substring
    assert store.resolve(data, "9") is None
    assert store.resolve(data, "nowhere") is None


def test_resharing_same_spot_updates_alias_instead_of_duplicating() -> None:
    data: dict = {}
    store.add_location(data, KYIV)
    loc, created = store.add_location(data, Place("Kyiv", 50.451, 30.521), "home")
    assert not created
    assert loc.alias == "home"
    assert len(store.list_locations(data)) == 1
    assert loc.card_name == "home · Kyiv, Ukraine"


def test_remove_adjusts_default() -> None:
    data: dict = {}
    for p in (KYIV, LVIV, PARIS):
        store.add_location(data, p)
    store.set_default(data, 2)  # Paris
    removed = store.remove_location(data, 0)  # Kyiv
    assert removed.place == KYIV
    assert store.get_default(data).place == PARIS
    store.remove_location(data, 1)  # Paris (now index 1), was default
    assert store.get_default(data).place == LVIV
    assert store.remove_location(data, 5) is None


def test_rename_and_set_default_bounds() -> None:
    data: dict = {}
    store.add_location(data, KYIV)
    assert store.rename_location(data, 0, "  dacha ").alias == "dacha"
    assert store.rename_location(data, 0, "").alias is None
    assert store.set_default(data, 3) is None


def test_limit() -> None:
    data: dict = {}
    for i in range(store.MAX_LOCATIONS):
        store.add_location(data, Place(f"p{i}", float(i), float(i)))
    with pytest.raises(ValueError):
        store.add_location(data, Place("one more", 80.0, 80.0))


def test_legacy_single_location_is_migrated() -> None:
    data = {"location": {"name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52}, "units": "metric"}
    locs = store.list_locations(data)
    assert len(locs) == 1 and locs[0].is_default and locs[0].place == KYIV
    assert "location" not in data
