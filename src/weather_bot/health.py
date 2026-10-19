"""Liveness signal for the container HEALTHCHECK.

The scheduler loop touches a heartbeat file every tick. It runs on the same event loop as
the Telegram polling, so a stale file means the bot is hung or the loop died; Docker's
``restart: unless-stopped`` alone only reacts to the process exiting.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

MAX_AGE_SECONDS = 120.0
DEFAULT_DATA_DIR = "./data"
HEARTBEAT_NAME = "heartbeat"


def beat(path: Path) -> None:
    path.touch()
    os.utime(path)


def is_alive(path: Path, now: float | None = None, max_age: float = MAX_AGE_SECONDS) -> bool:
    try:
        age = (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return False
    return age < max_age


def main() -> int:
    data_dir = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR))
    return 0 if is_alive(data_dir / HEARTBEAT_NAME) else 1


if __name__ == "__main__":
    sys.exit(main())
