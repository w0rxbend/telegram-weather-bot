"""Crash-safe pickle persistence.

PTB's ``PicklePersistence`` truncates the state file and then pickles into it, so a crash,
OOM kill or failing dump in between leaves an empty or partial file and loses every user's
saved locations. This subclass writes to a sibling temp file and atomically renames it.
"""

from __future__ import annotations

import os
import stat
from typing import Any

from telegram.ext import PicklePersistence

OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR  # saved coordinates are personal data


class AtomicPicklePersistence(PicklePersistence[Any, Any, Any]):
    def _dump_singlefile(self) -> None:
        target = self.filepath
        temp = target.with_name(f"{target.name}.tmp")
        self.filepath = temp
        try:
            super()._dump_singlefile()
            temp.chmod(OWNER_ONLY)
            os.replace(temp, target)
        finally:
            self.filepath = target
            temp.unlink(missing_ok=True)
