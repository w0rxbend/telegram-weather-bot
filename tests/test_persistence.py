from __future__ import annotations

import pickle
import sqlite3
import stat
from pathlib import Path

import pytest

from weather_bot.legacy_state import import_pickle_state
from weather_bot.persistence import SqlitePersistence


async def test_state_round_trips_with_owner_only_mode(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    store = SqlitePersistence(path)
    await store.update_user_data(1, {"locations": [{"name": "Київ", "lat": 50.45}]})
    await store.update_bot_data({"places": {"50.45,30.52": "Kyiv"}})
    await store.flush()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    reloaded = SqlitePersistence(path)
    assert (await reloaded.get_user_data())[1] == {"locations": [{"name": "Київ", "lat": 50.45}]}
    assert await reloaded.get_bot_data() == {"places": {"50.45,30.52": "Kyiv"}}
    assert await reloaded.get_chat_data() == {}


async def test_unchanged_rows_are_not_rewritten(tmp_path: Path) -> None:
    store = SqlitePersistence(tmp_path / "s.sqlite3")
    await store.update_user_data(1, {"a": 1})
    before = store._db.total_changes
    await store.update_user_data(1, {"a": 1})
    assert store._db.total_changes == before
    await store.update_user_data(1, {"a": 2})
    assert store._db.total_changes > before


async def test_drop_user_data(tmp_path: Path) -> None:
    store = SqlitePersistence(tmp_path / "s.sqlite3")
    await store.update_user_data(1, {"a": 1})
    await store.drop_user_data(1)
    assert await store.get_user_data() == {}


async def test_unserialisable_data_fails_loudly_and_writes_nothing(tmp_path: Path) -> None:
    store = SqlitePersistence(tmp_path / "s.sqlite3")
    with pytest.raises(TypeError):
        await store.update_user_data(1, {"bad": {1, 2}})
    assert await store.get_user_data() == {}


def test_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "s.sqlite3"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.close()
    with pytest.raises(RuntimeError, match="schema v99"):
        SqlitePersistence(path)


async def test_pickle_import_is_one_off(tmp_path: Path) -> None:
    legacy = tmp_path / "bot_state.pickle"
    legacy.write_bytes(
        pickle.dumps(
            {"user_data": {7: {"units": "imperial"}}, "bot_data": {"places": {"k": "Lviv"}}}
        )
    )
    store = SqlitePersistence(tmp_path / "s.sqlite3")
    assert import_pickle_state(legacy, store) is True
    assert not legacy.exists()
    assert (tmp_path / "bot_state.pickle.migrated").exists()
    assert await store.get_user_data() == {7: {"units": "imperial"}}
    assert await store.get_bot_data() == {"places": {"k": "Lviv"}}
    assert import_pickle_state(legacy, store) is False


async def test_pickle_import_skipped_when_store_has_data(tmp_path: Path) -> None:
    legacy = tmp_path / "bot_state.pickle"
    legacy.write_bytes(pickle.dumps({"user_data": {1: {"x": 1}}}))
    store = SqlitePersistence(tmp_path / "s.sqlite3")
    await store.update_user_data(2, {"y": 2})
    assert import_pickle_state(legacy, store) is False
    assert legacy.exists()
