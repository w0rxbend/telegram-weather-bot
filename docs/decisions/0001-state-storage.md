# 0001 — Replace the pickle state file with SQLite

Status: accepted (decision only; implementation not started). Closes the decision part of F-20.

## Context
`bot_state.pickle` holds per-user data (saved places, schedules, units) and shared `bot_data`.
Problems: every flush rewrites all users; unpickling a tampered file executes code; no schema
version, so no migration path. The data is small, key-value shaped and written by one process.

## Options
| Option | For | Against |
|---|---|---|
| **SQLite** (stdlib `sqlite3`) | No new dependency; transactional, crash-safe (WAL); per-row writes; inspectable with `sqlite3`; `user_version` for migrations; works on amd64 and arm64 images | Needs a small `BasePersistence` adapter |
| RocksDB / LevelDB | Fast KV | Native wheels (`rocksdict`, `plyvel`) must build for `linux/arm64/v8`, which CI publishes; larger image; no ad-hoc inspection; no schema migrations; speed is irrelevant at this size |
| Keep pickle | No work | The problems above |
| JSON file | Simple, safe to load | Rewrites everything per flush; no transactions |

## Decision
SQLite via the stdlib, tables `user_data(user_id, json)`, `chat_data(chat_id, json)`,
`bot_data(key, json)`, `meta(schema_version)`. Values are JSON, not pickle.

## Implementation plan (needs your go-ahead; touches production data)
1. `SqlitePersistence(BasePersistence)` in `persistence.py`, `update_*` writes only the changed row
   in a transaction, WAL on, file mode 0600.
2. Check that everything stored in `user_data`/`bot_data` is JSON-serialisable (tuples, `datetime`,
   sets need explicit encoding); add round-trip tests.
3. One-off import: on first start, if `bot_state.pickle` exists and the DB is empty, load the
   pickle once, write the rows, rename the pickle to `.migrated`. Test it on a copy of the
   production volume first.
4. Remove `AtomicPicklePersistence`, the `pickle` import and the `# nosec B403/B301` markers in `main.py`.
