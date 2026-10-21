"""One-off import of the old ``bot_state.pickle`` into the SQLite store."""

from __future__ import annotations

import logging
import pickle  # nosec B403
import time
from pathlib import Path
from typing import Any

from weather_bot.persistence import SqlitePersistence

log = logging.getLogger(__name__)


def quarantine_corrupt_state(path: Path) -> None:
    """Move an unreadable pickle aside so a bad file cannot crash-loop the bot."""
    if not path.exists():
        return
    # Safe by construction: this is the bot's own state file in DATA_DIR, never user input.
    try:
        with path.open("rb") as fh:
            pickle.load(fh)  # noqa: S301  # nosec B301
    except Exception as exc:  # noqa: BLE001 - any unpickling failure counts
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        path.rename(backup)
        log.error("State file %s was unreadable (%s); moved to %s", path, exc, backup)


def import_pickle_state(legacy: Path, store: SqlitePersistence) -> bool:
    """Copy users and shared data from ``legacy`` into an empty store; rename the pickle after.

    Returns True when an import happened. Does nothing if the store already has data or the
    pickle is missing, so it is safe to call on every start.
    """
    if not legacy.exists() or not store.is_empty():
        return False
    with legacy.open("rb") as fh:
        snapshot: dict[str, Any] = pickle.load(fh)  # noqa: S301  # nosec B301
    user_data = snapshot.get("user_data") or {}
    bot_data = snapshot.get("bot_data") or {}
    store.import_state(user_data, bot_data)
    done = legacy.with_name(f"{legacy.name}.migrated")
    legacy.rename(done)
    log.info("Imported %d users from %s (kept as %s)", len(user_data), legacy, done)
    return True
