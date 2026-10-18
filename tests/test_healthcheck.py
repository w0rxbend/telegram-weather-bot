from __future__ import annotations

import os
from pathlib import Path

from weather_bot import healthcheck


def test_fresh_beat_is_healthy(tmp_path: Path) -> None:
    beat_file = tmp_path / "heartbeat"
    healthcheck.beat(beat_file)
    assert healthcheck.is_healthy(beat_file)


def test_stale_beat_is_unhealthy(tmp_path: Path) -> None:
    beat_file = tmp_path / "heartbeat"
    healthcheck.beat(beat_file)
    os.utime(beat_file, (0, 0))
    assert not healthcheck.is_healthy(beat_file)


def test_missing_file_is_unhealthy(tmp_path: Path) -> None:
    assert not healthcheck.is_healthy(tmp_path / "nope")
