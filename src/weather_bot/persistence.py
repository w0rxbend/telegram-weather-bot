"""Crash-safe persistence.

PTB's ``PicklePersistence`` truncates the state file and then pickles into it, so a crash
or container stop in between destroys every user's data. This subclass writes a temporary
file next to the target and atomically renames it over the real one.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from telegram.ext import PicklePersistence

STATE_FILE_MODE = 0o600  # saved coordinates are personal data


class AtomicPicklePersistence(PicklePersistence):
    def _dump_singlefile(self) -> None:
        target = Path(self.filepath)
        tmp = target.with_name(f"{target.name}.tmp")
        self.filepath = tmp
        try:
            super()._dump_singlefile()
            self._flush_and_replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        finally:
            self.filepath = target

    @staticmethod
    def _flush_and_replace(tmp: Path, target: Path) -> None:
        fd = os.open(tmp, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        tmp.chmod(STATE_FILE_MODE)
        tmp.replace(target)
