from __future__ import annotations

import pickle
import stat
from pathlib import Path

import pytest
from telegram.ext import _picklepersistence

from weather_bot.persistence import AtomicPicklePersistence


async def test_state_round_trips_with_owner_only_mode(tmp_path: Path) -> None:
    path = tmp_path / "state.pickle"
    store = AtomicPicklePersistence(filepath=path)
    await store.update_user_data(1, {"locations": [{"name": "Kyiv"}]})
    await store.flush()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    reloaded = AtomicPicklePersistence(filepath=path)
    assert (await reloaded.get_user_data())[1] == {"locations": [{"name": "Kyiv"}]}


async def test_failed_dump_leaves_previous_state_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.pickle"
    good = AtomicPicklePersistence(filepath=path)
    await good.update_user_data(1, {"units": "metric"})
    await good.flush()
    before = path.read_bytes()

    def explode(self: object, obj: object) -> None:
        good.filepath.write_bytes(b"partial")  # at this point filepath is the temp file
        raise pickle.PicklingError("boom")

    monkeypatch.setattr(_picklepersistence._BotPickler, "dump", explode)
    with pytest.raises(pickle.PicklingError):
        await good.update_user_data(2, {"units": "imperial"})

    assert path.read_bytes() == before
    assert not [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert good.filepath == path
