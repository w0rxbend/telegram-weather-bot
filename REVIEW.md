# Review: hardening pass (2026-10-18)

## Executive summary
- **Before:** 139 tests green, ruff clean, but `mypy --strict` had 54 errors, `poetry.lock` pinned
  packages with 12 known CVEs (and the Docker image is built from it), full `Update` objects
  (message text, coordinates) were logged, and the state file could be destroyed by a crash.
- **After:** 193 tests green, ruff/format/mypy `--strict`/bandit/pip-audit all clean; CI now runs all
  of them. PII is out of logs, state writes are atomic (0600), per-user locking and rate limiting
  are in place, config is validated at startup, container is read-only with a healthcheck.
- **Top remaining risks:** third-party GitHub Actions are not pinned to SHAs (F-18); state is still a
  pickle file (F-20); no image vulnerability scan (F-19).
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
| F-18 | High | `docker-ci.yml` (`appleboy/telegram-action@master`, `ssh-action@v1`, `scp-action@v1`, …) | Mutable refs run with Docker Hub + SSH secrets | — | **Deferred** | — |
| F-19 | Medium | `docker-ci.yml` | No image vulnerability scan | — | **Deferred** | — |
| F-20 | Medium | `persistence.py` / pickle | Pickle state: rewrites all users on flush, unsafe if tampered with, no migration | — | **Deferred** | — |
| F-21 | Low | `geocode.py`, `weather.py` | No response size limit on outbound calls | `httpio.read_json_capped` (512 KiB, streamed); oversized → fallback / `WeatherError` | Fixed (2026-10-20 follow-up) | see `git log` |
| F-22 | Medium | `scheduler.py`, `bot.py` | Render per user (not per place) at popular slots; no render semaphore | — | **Deferred** (TODO.md P1/P2) | — |
| F-23 | Low | `bot.py` `/schedule` | Any group member can schedule sends to a group | — | **Deferred** (product decision) | — |
| F-24 | Low | `runtime.py`, `cache.py`, `bot._card_limiter` | Module-level mutable singletons | — | **Accepted** (documented in CODING_STANDARDS.md) | — |
| F-25 | Low | `bot.py` `_remember_place` | Shared `bot_data["places"]` can be primed by any user (stale label only) | — | **Deferred** | — |

Tooling and standards: 174be60, lock sync: see `git log`.

## Deferred — exact action required from you
- **F-18:** pin each third-party action to a commit SHA, e.g. `uses: appleboy/ssh-action@<40-char sha> # v1.x`.
  I could not resolve SHAs from this session (GitHub access is scoped to this repo). Dependabot
  (added) will keep them current once pinned. Pin `appleboy/telegram-action` first (`@master`).
- **F-19:** add `aquasecurity/trivy-action` (fail on HIGH/CRITICAL) after the build step.
- **F-20:** decide whether to move to SQLite (see `TODO.md`); needs a one-off migration run against a copy of the production volume.
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
