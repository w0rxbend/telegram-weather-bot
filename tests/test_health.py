from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather_bot import health, scheduler
from weather_bot.config import Settings


def test_missing_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    assert not health.is_alive(tmp_path / "heartbeat")


def test_fresh_and_stale_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat"
    health.beat(path)
    now = path.stat().st_mtime
    assert health.is_alive(path, now=now + 10)
    assert not health.is_alive(path, now=now + health.MAX_AGE_SECONDS + 1)


def test_cli_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert health.main() == 1
    health.beat(tmp_path / health.HEARTBEAT_NAME)
    assert health.main() == 0


def test_settings_heartbeat_name_matches_healthcheck(tmp_path: Path) -> None:
    settings = Settings("t", tmp_path, 1.0, "ua")
    assert settings.heartbeat_file.name == health.HEARTBEAT_NAME


async def test_scheduler_loop_beats_even_when_tick_fails(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat"
    app = SimpleNamespace(user_data=None)  # tick raises TypeError on .items()
    task = asyncio.create_task(scheduler.scheduler_loop(app, interval=0.01, heartbeat=path))
    await asyncio.sleep(0.05)
    task.cancel()
    assert path.exists()


async def test_scheduler_loop_survives_a_failing_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = 0

    async def count_tick(app: object) -> int:
        nonlocal ticks
        ticks += 1
        return 0

    monkeypatch.setattr(scheduler, "tick", count_tick)
    monkeypatch.setattr(scheduler, "alert_tick", count_tick)
    # A directory where the file should be: touch() raises an OSError, as a full disk would.
    blocked = tmp_path / "missing-dir" / "heartbeat"
    task = asyncio.create_task(
        scheduler.scheduler_loop(SimpleNamespace(), interval=0.01, heartbeat=blocked)
    )
    await asyncio.sleep(0.1)
    assert not task.done()  # before the fix the first OSError ended the loop for good
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert ticks > 2
