"""Crash-safe variant of PTB's single-file pickle persistence.

``PicklePersistence`` truncates the state file and then pickles into it, so a crash, OOM kill
or container stop in between leaves an empty or partial file and loses every user's data.
Here the dump goes to a sibling temp file first and is moved over the real one with
``os.replace`` (atomic on the same filesystem).
"""

from __future__ import annotations

import os
from pathlib import Path

from telegram.ext import PicklePersistence


class AtomicPicklePersistence(PicklePersistence):
    def _dump_singlefile(self) -> None:
        final = Path(self.filepath)
        temp = final.with_name(f"{final.name}.tmp")
        self.filepath = temp  # the parent implementation writes to ``self.filepath``
        try:
            super()._dump_singlefile()
            os.replace(temp, final)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        finally:
            self.filepath = final
