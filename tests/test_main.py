from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from weather_bot.main import quarantine_corrupt_state
from weather_bot.persistence import AtomicPicklePersistence


def test_quarantine_moves_unreadable_state(tmp_path: Path) -> None:
    state = tmp_path / "bot_state.pickle"
    state.write_bytes(b"\x80\x05not a pickle")
    quarantine_corrupt_state(state)
    assert not state.exists()
    assert len(list(tmp_path.glob("bot_state.pickle.corrupt-*"))) == 1


def test_quarantine_keeps_valid_state(tmp_path: Path) -> None:
    state = tmp_path / "bot_state.pickle"
    state.write_bytes(pickle.dumps({"user_data": {}}))
    quarantine_corrupt_state(state)
    assert state.exists()


def test_quarantine_ignores_missing_file(tmp_path: Path) -> None:
    quarantine_corrupt_state(tmp_path / "missing.pickle")


def test_atomic_persistence_keeps_old_state_when_dump_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "bot_state.pickle"
    persistence = AtomicPicklePersistence(filepath=state)
    persistence.user_data = {1: {"units": "metric"}}
    persistence._dump_singlefile()
    good = state.read_bytes()

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("weather_bot.persistence.PicklePersistence._dump_singlefile", explode)
    with pytest.raises(OSError, match="disk full"):
        persistence._dump_singlefile()
    assert state.read_bytes() == good
    assert not list(tmp_path.glob("*.tmp"))
    assert persistence.filepath == state
