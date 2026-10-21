from __future__ import annotations

import pickle
from pathlib import Path

from weather_bot.legacy_state import quarantine_corrupt_state


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
