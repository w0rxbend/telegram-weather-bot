# Review and hardening — 2026-10-19

Skills loaded: none were exposed for Python, testing or security in this session (only generic
`code-review`/`security-review`, not invoked). The review was done by hand, with ruff, mypy,
bandit and pip-audit.

## Executive summary

- **Before:** 139 tests green, ruff clean, **mypy 36 errors**, pip-audit clean, bandit 1 Medium (pickle load). No secrets in git history.
- **After:** 154 tests green, ruff/format clean, **mypy --strict 0 errors**, pip-audit clean, bandit clean. CI now runs all of them.
- **Fixed:** a hang in the forecast cache when a fetch is cancelled (F-01), unvalidated NaN/out-of-range callback coordinates (F-02), non-atomic state writes (F-03), edited/live-location updates re-triggering renders (F-06).
- **Top remaining risks (Deferred):** pickle persistence (D-01), no per-chat limit on who can attach a schedule to a group (D-02), unpinned base-image digests (D-03).
- Branch: `claude/dazzling-heisenberg-3xhgnc` (the session mandated this branch, instead of `chore/review-hardening-<date>`).

## Findings

| ID | Severity | Location | Issue | Fix | Status | Commit |
|----|----------|----------|-------|-----|--------|--------|
| F-01 | High | `cache.py` `ForecastCache.get` | Waiters on a coalesced fetch hang forever if the fetching task is cancelled or raises a non-`WeatherError` | Fail the shared future on every exit path; regression test | Fixed | 3b21236 |
| F-02 | High | `bot.py` `_parse_callback` | `float()` accepts `nan`/`inf`/out-of-range from client-controlled `callback_data`; reaches Open-Meteo and the cache key | Finite + range check; tests | Fixed | 3b21236 |
| F-03 | Medium | `main.py` (PTB `PicklePersistence`) | Dump truncates the state file first; a crash mid-write loses all user data | `AtomicPicklePersistence` (temp file + `os.replace`); test | Fixed | 6f82000 |
| F-04 | Medium | `config.py:39`, `cache.py:24` | `float(os.getenv(...))` unvalidated; TTL parsed at import time | `_positive_float` in `Settings`, fail fast; tests | Fixed | 6f82000 |
| F-05 | Medium | `scheduler.py` `_send`, `main.py` | No flood-control handling: `RetryAfter` on a busy slot drops the card | `AIORateLimiter` + one explicit `RetryAfter` retry; test | Fixed | 982f70b |
| F-06 | Medium | `main.py` `run_polling` | Edited messages (incl. live-location edits) re-ran geocoding and rendering | `allowed_updates=[message, callback_query]` | Fixed | 982f70b |
| F-07 | Medium | `bot.py` `_build_card`, `main.py` `concurrent_updates(True)` | Unbounded concurrent CPU-heavy renders | Semaphore sized to CPU count | Fixed | 982f70b |
| F-08 | Low | `bot.py` `on_error`, `post_shutdown`, `scheduler.stop` | `except…: pass` hides a failed error notice | Log it; `contextlib.suppress` elsewhere | Fixed | 982f70b |
| F-09 | Medium | `bot.py`, `scheduler.py`, `main.py`, `geocode.py` | 36 mypy errors; no type check in CI | Typed accessors/aliases; `mypy --strict` in CI | Fixed | a9e57e7 |
| F-10 | Low | `.github/workflows/ci.yml` | Default token permissions; no mypy/bandit/pip-audit | `permissions: contents: read`, new steps | Fixed | 2a1d546 |
| F-11 | Low | repo | No documented standards, pre-commit, bandit/pip-audit config | `CODING_STANDARDS.md`, `.pre-commit-config.yaml`, pyproject config | Fixed | 2a1d546 |
| D-01 | Medium | `main.py`, `TODO.md` P1 | Single pickle file: rewrites all users, loads on startup, code execution if the file is tampered with | — | Deferred | — |
| D-02 | Medium | `bot.py` `_apply_schedule` | `/schedule` stores `message.chat_id`; in a group any member can make the bot post there on a timer | — | Deferred | — |
| D-03 | Low | `Dockerfile` | Base images referenced by tag, not digest; no `HEALTHCHECK` | — | Deferred | — |
| D-04 | Low | `scheduler.py` `tick` | Renders once per user instead of once per place (CPU at scale; `TODO.md` P1) | — | Deferred | — |

## Facts (verified by running)

- Baseline: `pytest -q` 139 passed; `ruff check`/`ruff format --check` clean; `mypy src` (strict) 36 errors; `pip-audit` no known vulnerabilities; `bandit -r src` 1 Medium (B301), 17 Low.
- Final: `pytest -q` 154 passed; `ruff check src tests scripts` and `ruff format --check` clean; `mypy` 0 errors in 23 files; `pip-audit --skip-editable` no known vulnerabilities; `bandit -q -c pyproject.toml -r src` exit 0.
- F-01's regression test fails on the old `cache.py` (checked) and passes on the fix.
- No bot-token-like string or `.env`/key file was found in git history (searched all branches).
- The bot has no webhook mode, no admin commands, no file uploads, no SQL and no `eval`/`exec`; reply texts built from user input are `html.escape`d where `parse_mode=HTML` is used.
- The container runs as a non-root user (uid 1000).

## Assumptions

- The default-branch workflow is a PR from the session branch into `main`.
- Telegram clients are untrusted: `callback_data` and all text are treated as hostile.
- Running as a single process with long polling is the intended deployment.

## Uncertainties

- `on_card_callback` answers the callback query twice on a forecast failure (`"Refreshing…"`, then an alert). Whether Telegram rejects the second answer was not tested against the live API, so it is left unchanged.
- `Dockerfile` builds were not run here (no Docker; `poetry-plugin-export` is not installed locally), so the image build with the refreshed `poetry.lock` is unverified.
- CI workflow changes were not executed on GitHub; the commands were run locally.
- `AtomicPicklePersistence` overrides PTB's private `_dump_singlefile`; a future PTB 22.x release could rename it (tests would catch that).

## Deferred items — action required from you

- **D-01 (pickle → SQLite):** product/migration decision. Approve a design (see `TODO.md`), and provide a copy of the production `bot_state.pickle` to test the one-off migration against.
- **D-02 (group schedules):** decide whether `/schedule` should work only in private chats (simple: reject when `chat.type != "private"`) or only for chat admins.
- **D-03 (image hardening):** needs registry access to look up the current `python:3.13-slim` digest to pin, and a decision on a health-check mechanism for a polling bot (e.g. a heartbeat file).
- **D-04 (render once per place):** performance work, needs a design for sharing `file_id`s across sends; see `TODO.md`.
- No secrets were found, so no rotation is required.
