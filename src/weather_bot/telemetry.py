"""Own usage telemetry: who uses the bot, how often, and for which cities.

Kept in a separate SQLite file (0600) so it can be inspected, backed up or deleted without
touching user state. Only aggregates are stored: per-user counters per action and per city
label. Coordinates, message text and chat ids are never recorded. Telemetry is best effort:
a storage error is logged and never reaches the user.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import sqlite3
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR
TOP_LIMIT = 10
MAX_CITY_LENGTH = 120
DAYS_SHOWN = 14
EXPORT_ROW_LIMIT = 200_000  # newest rows; keeps the CSV under Telegram's upload limit
SECONDS_PER_DAY = 86_400
ALIAS_SEPARATOR = " · "  # SavedLocation.card_name is "<alias> · <place>"

_actor: ContextVar[int | None] = ContextVar("telemetry_actor", default=None)


@contextmanager
def acting_as(user_id: int) -> Iterator[None]:
    """Attribute cards built inside the block to ``user_id``."""
    token = _actor.set(user_id)
    try:
        yield
    finally:
        _actor.reset(token)


@dataclass(frozen=True)
class Ranked:
    label: str
    count: int


@dataclass(frozen=True)
class UsageReport:
    users: int
    events: int
    cards: int
    top_users: list[Ranked]
    top_cities: list[Ranked]
    top_events: list[Ranked]
    daily: list[Ranked] = field(default_factory=list)  # last DAYS_SHOWN UTC days, oldest first


def _csv_safe(value: str) -> str:
    """Stop spreadsheet apps from running a cell as a formula."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def city_label(place_name: str) -> str:
    """The real place from a card name, without the user's private slot alias."""
    return place_name.rsplit(ALIAS_SEPARATOR, 1)[-1].strip()[:MAX_CITY_LENGTH]


class UsageTelemetry:
    def __init__(self, path: Path) -> None:
        path.touch(mode=OWNER_ONLY, exist_ok=True)
        path.chmod(OWNER_ONLY)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, language TEXT,
                first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                user_id INTEGER NOT NULL, event TEXT NOT NULL, count INTEGER NOT NULL,
                last_seen INTEGER NOT NULL, PRIMARY KEY (user_id, event));
            CREATE TABLE IF NOT EXISTS cities (
                user_id INTEGER NOT NULL, city TEXT NOT NULL, count INTEGER NOT NULL,
                last_seen INTEGER NOT NULL, PRIMARY KEY (user_id, city));
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
                user_id INTEGER NOT NULL, event TEXT NOT NULL, city TEXT);
            CREATE INDEX IF NOT EXISTS event_log_ts ON event_log (ts);
            CREATE INDEX IF NOT EXISTS event_log_user ON event_log (user_id, ts);
            """
        )

    # --- synchronous writes (run in a worker thread) --------------------------------------

    def _write(self, *statements: tuple[str, tuple[object, ...]]) -> None:
        try:
            with self._lock:
                self._db.execute("BEGIN")
                try:
                    for sql, params in statements:
                        self._db.execute(sql, params)
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise
                self._db.execute("COMMIT")
        except sqlite3.Error as exc:
            log.warning("Telemetry write failed: %s", exc)

    def _record(
        self,
        user_id: int,
        username: str | None,
        language: str | None,
        event: str,
        city: str | None = None,
    ) -> None:
        """One transaction: the raw log row plus the user and counter rows derived from it."""
        now = int(time.time())
        statements: list[tuple[str, tuple[object, ...]]] = [
            (
                "INSERT INTO users (user_id, username, language, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "username = COALESCE(excluded.username, username), "
                "language = COALESCE(excluded.language, language), "
                "last_seen = excluded.last_seen",
                (user_id, username, language, now, now),
            ),
            (
                "INSERT INTO events (user_id, event, count, last_seen) VALUES (?, ?, 1, ?) "
                "ON CONFLICT(user_id, event) DO UPDATE SET count = count + 1, "
                "last_seen = excluded.last_seen",
                (user_id, event, now),
            ),
            (
                "INSERT INTO event_log (ts, user_id, event, city) VALUES (?, ?, ?, ?)",
                (now, user_id, event, city),
            ),
        ]
        if city is not None:
            statements.append(
                (
                    "INSERT INTO cities (user_id, city, count, last_seen) VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(user_id, city) DO UPDATE SET count = count + 1, "
                    "last_seen = excluded.last_seen",
                    (user_id, city, now),
                )
            )
        self._write(*statements)

    def _daily(self, now: datetime) -> list[Ranked]:
        today = int(now.timestamp()) // SECONDS_PER_DAY
        first = today - DAYS_SHOWN + 1
        rows = self._db.execute(
            "SELECT ts / ?, COUNT(*) FROM event_log WHERE ts >= ? GROUP BY 1",
            (SECONDS_PER_DAY, first * SECONDS_PER_DAY),
        ).fetchall()
        counts = dict(rows)
        return [
            Ranked(
                (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(days=day)).strftime("%d"),
                int(counts.get(day, 0)),
            )
            for day in range(first, today + 1)
        ]

    def _export_csv(self) -> str:
        with self._lock:
            rows = self._db.execute(
                "SELECT l.ts, l.user_id, COALESCE(u.username, ''), l.event, COALESCE(l.city, '') "
                "FROM event_log l LEFT JOIN users u USING (user_id) "
                "ORDER BY l.id DESC LIMIT ?",
                (EXPORT_ROW_LIMIT,),
            ).fetchall()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["time_utc", "user_id", "username", "event", "city"])
        for ts, user_id, username, event, city in reversed(rows):
            stamp = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([stamp, user_id, _csv_safe(username), event, _csv_safe(city)])
        return out.getvalue()

    def _report(self) -> UsageReport:
        def ranked(sql: str) -> list[Ranked]:
            return [Ranked(str(label), int(n)) for label, n in self._db.execute(sql, (TOP_LIMIT,))]

        with self._lock:
            users = self._db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            events = self._db.execute("SELECT COALESCE(SUM(count), 0) FROM events").fetchone()[0]
            cards = self._db.execute("SELECT COALESCE(SUM(count), 0) FROM cities").fetchone()[0]
            return UsageReport(
                users=users,
                events=events,
                cards=cards,
                top_users=ranked(
                    "SELECT COALESCE('@' || u.username, CAST(u.user_id AS TEXT)) || ' (' || "
                    "u.user_id || ')', SUM(e.count) AS n FROM events e "
                    "JOIN users u USING (user_id) GROUP BY u.user_id ORDER BY n DESC LIMIT ?"
                ),
                top_cities=ranked(
                    "SELECT city, SUM(count) AS n FROM cities GROUP BY city ORDER BY n DESC LIMIT ?"
                ),
                daily=self._daily(datetime.now(UTC)),
                top_events=ranked(
                    "SELECT event, SUM(count) AS n FROM events GROUP BY event "
                    "ORDER BY n DESC LIMIT ?"
                ),
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- async API ------------------------------------------------------------------------

    async def record_event(
        self, user_id: int, event: str, username: str | None = None, language: str | None = None
    ) -> None:
        await asyncio.to_thread(self._record, user_id, username, language, event)

    async def record_card(self, city: str, kind: str) -> None:
        """Log one delivered card for the current actor (see :func:`acting_as`)."""
        user_id = _actor.get()
        if user_id is None:
            return
        await asyncio.to_thread(self._record, user_id, None, None, f"card:{kind}", city_label(city))

    async def report(self) -> UsageReport:
        return await asyncio.to_thread(self._report)

    async def export_csv(self) -> str:
        """The raw event log (time, user, event, city), newest ``EXPORT_ROW_LIMIT`` rows."""
        return await asyncio.to_thread(self._export_csv)
