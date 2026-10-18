"""Liveness heartbeat: the scheduler loop touches a file, Docker checks its age."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DEFAULT_DATA_DIR = "./data"
MAX_AGE_SECONDS = 120.0


def beat(path: Path) -> None:
    path.touch()


def is_healthy(path: Path, now: float | None = None, max_age: float = MAX_AGE_SECONDS) -> bool:
    try:
        age = (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age


def main() -> int:
    heartbeat = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR)) / "heartbeat"
    return 0 if is_healthy(heartbeat) else 1


if __name__ == "__main__":
    sys.exit(main())
