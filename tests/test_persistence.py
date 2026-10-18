from __future__ import annotations

import stat
from pathlib import Path

import pytest

from weather_bot.persistence import AtomicPicklePersistence


async def test_update_writes_loadable_state_with_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "state.pickle"
    persistence = AtomicPicklePersistence(filepath=path)
    await persistence.update_user_data(1, {"locations": [1]})
    await persistence.flush()
    reloaded = AtomicPicklePersistence(filepath=path)
    assert (await reloaded.get_user_data())[1] == {"locations": [1]}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


async def test_failed_dump_keeps_previous_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.pickle"
    persistence = AtomicPicklePersistence(filepath=path)
    await persistence.update_user_data(1, {"v": "good"})
    await persistence.flush()
    good = path.read_bytes()

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    persistence.user_data[1] = {"v": "new"}
    monkeypatch.setattr("telegram.ext._picklepersistence._BotPickler.dump", explode)
    with pytest.raises(RuntimeError):
        await persistence.flush()
    assert path.read_bytes() == good
    assert not list(tmp_path.glob("*.tmp"))
    assert persistence.filepath == path
