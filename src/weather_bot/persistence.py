"""SQLite-backed PTB persistence.

Replaces the pickle state file (see ``docs/decisions/0001-state-storage.md``): rows are JSON,
so a tampered file cannot execute code, only the rows that changed are written, and every
write is a transaction. Only ``user_data`` and ``bot_data`` are used by this bot; chat data,
callback data and conversations are not stored.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import stat
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from telegram.ext import BasePersistence, PersistenceInput

OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR  # saved coordinates are personal data
SCHEMA_VERSION = 1
BOT_DATA_KEY = "bot_data"
CallbackData = tuple[list[tuple[str, float, dict[str, Any]]], dict[str, str]]

_UPSERT_USER = (
    "INSERT INTO user_data (user_id, json) VALUES (?, ?) "
    "ON CONFLICT(user_id) DO UPDATE SET json = excluded.json"
)
_UPSERT_BOT = (
    "INSERT INTO bot_data (key, json) VALUES (?, ?) "
    "ON CONFLICT(key) DO UPDATE SET json = excluded.json"
)


def _encode(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


class SqlitePersistence(BasePersistence[dict[str, Any], dict[str, Any], dict[str, Any]]):
    def __init__(self, path: Path) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=True, chat_data=False, user_data=True, callback_data=False
            )
        )
        self._lock = threading.Lock()
        self._written: dict[str, str] = {}  # row id -> last JSON written, to skip no-op writes
        self._db = self._open(path)

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        path.touch(mode=OWNER_ONLY, exist_ok=True)
        path.chmod(OWNER_ONLY)
        db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            db.close()
            raise RuntimeError(
                f"{path} has schema v{version}; this bot supports v{SCHEMA_VERSION}."
            )
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER PRIMARY KEY, json TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS bot_data (key TEXT PRIMARY KEY, json TEXT)")
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return db

    # --- synchronous row access (run in a worker thread by the async API) -------------------

    def put_user(self, user_id: int, data: Mapping[str, Any]) -> None:
        payload = _encode(data)
        with self._lock:
            if self._written.get(f"user:{user_id}") == payload:
                return
            self._db.execute(_UPSERT_USER, (user_id, payload))
            self._written[f"user:{user_id}"] = payload

    def put_bot_data(self, data: Mapping[str, Any]) -> None:
        payload = _encode(data)
        with self._lock:
            if self._written.get("bot") == payload:
                return
            self._db.execute(_UPSERT_BOT, (BOT_DATA_KEY, payload))
            self._written["bot"] = payload

    def is_empty(self) -> bool:
        with self._lock:
            users = self._db.execute("SELECT COUNT(*) FROM user_data").fetchone()[0]
            bot = self._db.execute("SELECT COUNT(*) FROM bot_data").fetchone()[0]
        return bool(users + bot == 0)

    def import_state(
        self, user_data: Mapping[int, Mapping[str, Any]], bot_data: Mapping[str, Any]
    ) -> None:
        """Write a whole snapshot in one transaction (used by the one-off pickle import)."""
        users = [(int(user_id), _encode(data)) for user_id, data in user_data.items()]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.executemany(_UPSERT_USER, users)
                self._db.execute(_UPSERT_BOT, (BOT_DATA_KEY, _encode(bot_data)))
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _load_users(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT user_id, json FROM user_data").fetchall()
            for user_id, payload in rows:
                self._written[f"user:{user_id}"] = payload
        return {int(user_id): json.loads(payload) for user_id, payload in rows}

    def _load_bot_data(self) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT json FROM bot_data WHERE key = ?", (BOT_DATA_KEY,)
            ).fetchone()
            if row is None:
                return {}
            self._written["bot"] = row[0]
        loaded: dict[str, Any] = json.loads(row[0])
        return loaded

    def _delete_user(self, user_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM user_data WHERE user_id = ?", (user_id,))
            self._written.pop(f"user:{user_id}", None)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- BasePersistence API ----------------------------------------------------------------

    async def get_bot_data(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._load_bot_data)

    async def update_bot_data(self, data: dict[str, Any]) -> None:
        await asyncio.to_thread(self.put_bot_data, data)

    async def refresh_bot_data(self, bot_data: dict[str, Any]) -> None:
        return None

    async def get_user_data(self) -> dict[int, dict[str, Any]]:
        return await asyncio.to_thread(self._load_users)

    async def update_user_data(self, user_id: int, data: dict[str, Any]) -> None:
        await asyncio.to_thread(self.put_user, user_id, data)

    async def refresh_user_data(self, user_id: int, user_data: dict[str, Any]) -> None:
        return None

    async def drop_user_data(self, user_id: int) -> None:
        await asyncio.to_thread(self._delete_user, user_id)

    async def get_chat_data(self) -> dict[int, dict[str, Any]]:
        return {}

    async def update_chat_data(self, chat_id: int, data: dict[str, Any]) -> None:
        return None

    async def refresh_chat_data(self, chat_id: int, chat_data: dict[str, Any]) -> None:
        return None

    async def drop_chat_data(self, chat_id: int) -> None:
        return None

    async def get_callback_data(self) -> CallbackData | None:
        return None

    async def update_callback_data(self, data: CallbackData) -> None:
        return None

    async def get_conversations(self, name: str) -> dict[tuple[int | str, ...], object]:
        return {}

    async def update_conversation(
        self, name: str, key: tuple[int | str, ...], new_state: object | None
    ) -> None:
        return None

    async def flush(self) -> None:
        """Rows are committed as they are written; nothing is buffered."""
        return None
