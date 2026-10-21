# Review: hardening pass (2026-10-18)

## Executive summary
- **Before:** 139 tests green, ruff clean, but `mypy --strict` had 54 errors, `poetry.lock` pinned
  packages with 12 known CVEs (and the Docker image is built from it), full `Update` objects
  (message text, coordinates) were logged, and the state file could be destroyed by a crash.
- **After:** 193 tests green, ruff/format/mypy `--strict`/bandit/pip-audit all clean; CI now runs all
  of them. PII is out of logs, state writes are atomic (0600), per-user locking and rate limiting
  are in place, config is validated at startup, container is read-only with a healthcheck.
- **Top remaining risks:** the SQLite state store (F-20) and the new SHA pins/Trivy step have not run against production or Actions yet.
- No secrets were found in the working tree or git history (regex scan for bot-token shapes and
  `*_KEY=`/`*_TOKEN=` literals). No rotation needed.

## Findings

| ID | Sev | Location | Issue | Fix | Status | Commit |
|----|-----|----------|-------|-----|--------|--------|
| F-01 | High | `poetry.lock` (anyio 3.7.0, certifi 2023.5.7, idna 3.4, python-dotenv 1.0.0) | 12 known vulnerabilities in the lock the Docker image is built from | `poetry update` of the four packages | Fixed | d19d296 |
| F-02 | High | `bot.py` `on_error` (was :725), `weather.py:250,260`, `geocode.py:60,88` | Whole `Update` and httpx errors (URL with coordinates / typed city) written to logs | Log ids only; `privacy.describe_error`; drop chained cause | Fixed | 7b6a464 |
| F-03 | Medium | `bot.py` `on_error` | Failing button press left the spinner running; reply failure swallowed with `except Exception: pass` | Answer callback; catch `TelegramError` and log | Fixed | 7b6a464 |
| F-04 | Medium | `bot.py` `_parse_callback`, `_slot_arg` | `callback_data` floats accepted `nan`/`inf`/out-of-range; `'²'.isdigit()` then `int()` crashed | Range check; ASCII digits only | Fixed | 2f8e580 |
| F-05 | Medium | `bot.py` `register_handlers` | Edited messages and channel posts reached handlers (`user_data` is `None` → crash) | `filters.UpdateType.MESSAGE` on all handlers | Fixed | 2f8e580 |
| F-06 | Medium | `main.py` `concurrent_updates(True)` + `bot.py` | Two updates of one user interleave read-modify-write of `user_data` | Per-user `asyncio.Lock` (`_guarded`) | Fixed | 7eadbd4 |
| F-07 | Medium | `bot.py` card handlers | No per-user limit on renders/uploads (CPU DoS) | `ratelimit.RateLimiter`, 10 cards/min/user | Fixed | 7eadbd4 |
| F-08 | High | `main.py` (PTB `PicklePersistence`) | Dump truncates the file first; crash mid-write loses all users' data; file world-readable | `AtomicPicklePersistence` (temp + `os.replace`, 0600) | Fixed | ac987d2 |
| F-09 | Medium | `scheduler.py` `_send` | `RetryAfter` (429) only logged → missed card; "chat not found" retried forever | Wait ≤60 s and retry once; remove schedule on vanished chat | Fixed | 55bbbd2 |
| F-10 | Low | `bot.py` `/add`, `/rename`; `locations.py` | Aliases stored verbatim (control / bidi chars) | `clean_alias` (NFKC, printable, ≤30) | Fixed | 97ece11 |
| F-11 | Low | `locations.py` `resolve` | `/weather ²` raised `ValueError` | `isascii()` guard | Fixed | 97ece11 |
| F-12 | Low | `config.py` | Token / timeout not validated; bad `HTTP_TIMEOUT` gave a raw `ValueError` | Validate at startup, never echo token | Fixed | 6d43a2c |
| F-13 | Low | `main.py` http client | Redirects followed, no connection cap | `follow_redirects=False`, `Limits(20)` | Fixed | 6d43a2c |
| F-14 | Medium | `Dockerfile`, `docker-compose.yaml` | No healthcheck; writable root fs; all caps | Heartbeat + `HEALTHCHECK`; `read_only`, `cap_drop: ALL`, `no-new-privileges` | Fixed (not run in Docker) | 42ec996 |
| F-15 | Low | `bot.py` (15× `assert`), `scheduler.py`, `main.py` | `assert` guards stripped by `-O`; 54 strict-typing errors; inaccessible messages crash | Typed accessors, annotations, `UnexpectedUpdateError` | Fixed | e739a8b |
| F-16 | Medium | `.github/workflows/docker-ci.yml:80` | `TG_BOT_TOKEN` interpolated into remote shell script; no `permissions:` | `envs:` input; `permissions: contents: read` | Fixed | 42ec996 |
| F-17 | Low | repo | No dependabot | `.github/dependabot.yml` (pip, actions, docker) | Fixed | 42ec996 |
| F-18 | High | `docker-ci.yml` (`appleboy/telegram-action@master`, `ssh-action@v1`, `scp-action@v1`, …) | Mutable refs run with Docker Hub + SSH secrets | Pinned all actions to SHAs (tag in comment) | Fixed (2026-10-21) | see git log |
| F-19 | Medium | `docker-ci.yml` | No image vulnerability scan | Trivy scan before push, fails on fixable HIGH/CRITICAL | Fixed (not run in Actions) | see git log |
| F-20 | Medium | `persistence.py` / pickle | Pickle state: rewrites all users on flush, unsafe if tampered with, no migration | `SqlitePersistence` (JSON rows, WAL, 0600) + one-off pickle import (`legacy_state.py`); see `docs/decisions/0001-state-storage.md` | Fixed (import untested on real data) | see git log |
| F-21 | Low | `geocode.py`, `weather.py` | No response size limit on outbound calls | `httpcap.get_capped` (1 MB, streamed) | Fixed (2026-10-21) | b4c7090 |
| F-26 | High | `poetry.lock` (certifi 2026.7.22) | PYSEC-2026-4320, new advisory since the last pass | `poetry update certifi` → 2026.10.19 | Fixed (2026-10-21) | 31752a3 |
| F-27 | Low | `main.py` (`SqlitePersistence.close` never called) | SQLite connection left open at shutdown (WAL not checkpointed cleanly) | Close the store in `post_shutdown` | Fixed (2026-10-21, second pass) | see git log |
| F-28 | Medium | `Dockerfile:2,15` vs `ci.yml` | Image moved to `python:3.14-slim` (Dependabot #43) but CI only tested 3.13 | CI matrix 3.13 + 3.14; suite run on 3.14 locally: 203 passed | Fixed | see git log |
| F-22 | Medium | `scheduler.py`, `bot.py` | Render per user (not per place) at popular slots; no render semaphore | — | **Deferred** (TODO.md P1/P2) | — |
| F-23 | Low | `bot.py` `/schedule` | Any group member can schedule sends to a group | — | **Deferred** (product decision) | — |
| F-24 | Low | `runtime.py`, `cache.py`, `bot._card_limiter` | Module-level mutable singletons | — | **Accepted** (documented in CODING_STANDARDS.md) | — |
| F-25 | Low | `bot.py` `_remember_place` | Shared `bot_data["places"]` can be primed by any user (stale label only) | — | **Deferred** | — |

Tooling and standards: 174be60, lock sync: see `git log`.

## Deferred — exact action required from you
- **F-20 deploy check:** before the first deploy, back up the data volume; after it, confirm the log line `Imported N users` and that `bot_state.pickle.migrated` exists next to `bot_state.sqlite3`. Rollback: stop the bot, delete the `.sqlite3*` files, rename `.migrated` back to `.pickle`, deploy the previous image.
- **F-22 / F-23:** product/capacity decisions; see `TODO.md`.
- **Deploy check:** after merge, run `docker compose up -d` and confirm `docker inspect --format '{{.State.Health.Status}}' <container>` becomes `healthy`, and that the bot starts with `read_only: true`.

## Facts (verified by running)
- Baseline: `pytest -q` 139 passed; `ruff check`/`ruff format --check` clean; `mypy --strict src` 54 errors;
  `bandit -r src` 19 issues (1 medium); `pip-audit` of the exported lock: 12 vulnerabilities.
- Final: `pytest -q` 193 passed; `ruff check src tests scripts` and `ruff format --check` clean; `mypy` (strict) clean on 26 files;
  `bandit -c pyproject.toml -r src` rc 0; `pip-audit -r <exported lock incl. dev> --no-deps --disable-pip` no known vulnerabilities.
- `docker compose config` accepts the new compose file.
- Framework: python-telegram-bot 22.8, polling (no webhook, so no secret_token to verify), Poetry, Python 3.13 image.

## Assumptions
- Work was done on the branch `claude/keen-clarke-jfbpll` (assigned by the environment) instead of
  `chore/review-hardening-<date>`; it already carried two earlier unmerged commits.
- 10 cards/minute/user is a sensible limit; adjust `ratelimit.DEFAULT_LIMIT`.
- Open-Meteo and Nominatim never answer with redirects (true at time of writing; not re-checked live).

## Uncertainties
- The Docker image was not built or run here; healthcheck and `read_only` are unexercised outside `docker compose config`.
- GitHub Actions were not executed; the CI workflow edits are YAML-validated only.
- Telegram was not contacted; behaviour of handlers is covered by unit tests with fake updates.
- `AtomicPicklePersistence` swaps `self.filepath` temporarily; safe because PTB dumps synchronously on the event loop, but re-check on PTB major upgrades.

## Follow-up pass (2026-10-21)
- Baseline: `pytest -q` 194 passed; ruff check/format clean; `mypy` strict clean (26 files); bandit clean;
  pip-audit (`poetry show` pins, `--no-deps --disable-pip`): 1 vulnerability (certifi, PYSEC-2026-4320).
- Final: 198 passed; ruff, mypy (27 files), bandit clean; pip-audit: no known vulnerabilities.
- Fixed F-26 and F-21. F-20 implemented (below). Remaining: F-22, F-23, F-25.
- Secret scan of full git history: only the `.env.example` placeholder matched a bot-token regex.
- Branch is `claude/dazzling-heisenberg-r7foh2` (environment-assigned), not `chore/review-hardening-<date>`.

- F-18/F-19 done in the follow-up commits; F-20 decision recorded in `docs/decisions/0001-state-storage.md`. The Trivy step and pinned SHAs have not run in GitHub Actions yet.

## Second pass (2026-10-21, after PR #49 merged)
- Baseline on `main` 584a81d: `poetry run pytest -q` 203 passed; `poetry run ruff check src tests scripts` and `ruff format --check` clean;
  `poetry run mypy` strict clean (28 files); `poetry run bandit -q -c pyproject.toml -r src` clean;
  `pip-audit -r <poetry show pins> --no-deps --disable-pip`: no known vulnerabilities. Same results after the fixes.
- Also ran the suite on Python 3.14.6 (uv venv, pins from `poetry show`): 203 passed.
- Reviewed the new `persistence.py` / `legacy_state.py`: row writes are transactional, schema version is checked, file is 0600. Fixed F-27, F-28.
- Uncertainty: the pickle import calls `json.dumps` on the old `user_data`; a value that is not JSON-serialisable would stop startup with `TypeError`
  (the pickle is left in place, so rollback is trivial). Current code only stores str/int/float/list/dict, but real data was not available to check.
- Docker image was not built here (docker daemon not exercised); Actions not run.
