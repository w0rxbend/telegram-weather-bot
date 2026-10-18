# Review: hardening pass (2026-10-18)

Scope: whole repository at `main` (dd9ff77). Reviewer role: senior Python / security.
Skills: no Python-, review-, testing- or security-specific skills were available in this
session (only generic harness skills such as `code-review`, `security-review`, `simplify`);
none were run, the review was done by reading the code and running the tools below.

## Executive summary

- **Before:** 139 tests green, ruff clean, pip-audit clean, but `mypy --strict` had 54 errors,
  bandit 18 findings, no type check / audit / coverage in CI, and several real defects:
  PII in logs, live-location edits spamming cards, racy `user_data`, non-atomic state file,
  no rate limiting, secrets interpolated into a deploy script.
- **After:** 12 commits. 183 tests green (89 % coverage, floor 85 %), ruff clean,
  `mypy --strict` clean, bandit clean, pip-audit clean. 17 findings fixed, 8 deferred.
- **Top remaining risks (deferred):** GitHub Actions pinned to mutable refs (F-19), state kept
  in a pickle file (F-18), no user data-erasure command (F-24).
- No secret was found in the working tree or git history (see Facts). Nothing to rotate.

## Findings

Severity: C = Critical, H = High, M = Medium, L = Low. Line numbers refer to `main` (dd9ff77).

| ID | Sev | Location | Issue | Fix | Status | Commit |
|---|---|---|---|---|---|---|
| F-01 | H | `bot.py:724` | `on_error` logged the whole `Update` (message text, coordinates, names) at ERROR. | Log `update_id` + user id + exception only. | Fixed | 072cbd3 |
| F-02 | M | `bot.py:239,654` | Warnings logged `Place` objects (exact coordinates). | Log the exception only. | Fixed | 072cbd3 |
| F-03 | H | `bot.py:766-767` | Handlers also received `edited_message` and channel posts. Live-location sharing sends an edit every few seconds, each treated as a new share (card + geocode per edit); channel posts have `user_data=None`. | `filters.UpdateType.MESSAGE` on every message/command handler. | Fixed | 534c35a |
| F-04 | M | `bot.py:767,763` | Free text answered (with geocoding) in every group chat; `/schedule` could be set in groups by any member. | Free text private-only; `/schedule` private-only with an explanatory reply elsewhere. | Fixed | 534c35a |
| F-05 | H | `main.py:62` | `concurrent_updates(True)`: two updates of one user ran in parallel on read-modify-write `user_data`. | `PerUserUpdateProcessor` (parallel across users, serial per user). | Fixed | 1c0907c |
| F-06 | M | `bot.py:650-657` | Refresh callback answered the query twice on forecast failure; Telegram rejects the second answer, user saw the generic error. | Failure notice is a chat reply. | Fixed | 699a230 |
| F-07 | L | `bot.py:618-623` | `callback_data` coordinates accepted `nan`, `inf`, out-of-range values. | Strict range/finite check. | Fixed | 699a230 |
| F-08 | M | `config.py:100-110` | No validation of token format; `HTTP_TIMEOUT` raised a bare `ValueError`, accepted `nan`/0. | `ConfigError`, regex for token (value never echoed), bounded timeout. | Fixed | f0d5486 |
| F-09 | L | `main.py:41-46` | HTTP client followed redirects and had no connection cap. | `follow_redirects=False`, `max_connections=20`. | Fixed | f0d5486 |
| F-10 | H | `main.py:61` (PTB `_dump_singlefile`) | State file truncated before pickling: a crash/stop mid-write lost all users' data. | `AtomicPicklePersistence`: temp file, fsync, rename, mode 0600. | Fixed | 59ec8c9 |
| F-11 | L | `bot.py:728` | `except Exception: pass` in `on_error`. | Catch `TelegramError`, log at debug. | Fixed | 072cbd3 |
| F-12 | M | `Dockerfile`, `scheduler.py` | No health check: a dead scheduler loop looked healthy. | Scheduler heartbeat file + `HEALTHCHECK`. | Fixed | fec3350 |
| F-13 | H | `docker-ci.yml:92-95`, `docker-compose.yaml` | `${{ secrets.TG_BOT_TOKEN }}` interpolated into the SSH script text; no `permissions:`; container ran with default caps and writable root fs. | Secrets via `envs:`, `permissions: contents: read`, compose `read_only`, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp`. | Fixed | fec3350 |
| F-14 | L | `locations.py:97,140` | Slot names stored verbatim (control / bidi characters, whitespace runs). | `normalize_alias` (NFKC, strip control/format, collapse, cap 30). | Fixed | 120d9a5 |
| F-15 | M | `bot.py` (15× `assert`) | `assert` used for input narrowing: removed by `-O`, and real updates arrive without `effective_message`. Inaccessible (>48 h) callback messages crashed. | Guards; `isinstance(message, Message)` in callbacks. | Fixed | 8a66dc4 |
| F-16 | M | `scheduler.py`, `main.py`, `bot.py`, … | `mypy --strict`: 54 errors; untyped functions; stale ignores. | Annotated, `_user()` helper, `App` alias. | Fixed | 8a66dc4 |
| F-17 | H | `bot.py` (`_send_card`, `on_card_callback`), `scheduler.py` | No rate limiting: any chat could pin the CPU with `/weather`/refresh spam; `RetryAfter` on scheduled sends dropped the card. | 10 cards/min/chat sliding window; scheduler waits `RetryAfter` (≤30 s) and retries once. | Fixed | ab30fc7 |
| F-18 | M | `main.py:27,61` | State persisted with pickle (code execution if the file were tampered with; rewrites all users each flush; no migrations). | — | Deferred | — |
| F-19 | H | `docker-ci.yml` | `appleboy/*@master`/`@v1` are mutable refs running with deploy secrets. | — (Dependabot for actions added in 20bd1cf) | Deferred | — |
| F-20 | L | `scheduler.py:_send` | Scheduler lazily imports private helpers from `bot.py` (transport imports transport; card building belongs in a service module). | — | Deferred | — |
| F-21 | L | `bot.py:_remember_place` | Place-name cache lives in persisted `bot_data`, shared across users, up to 5000 entries. | — | Deferred | — |
| F-22 | L | `render/`, `bot.py:_build_card` | Renders are CPU bound with no global concurrency cap (per-chat limit now bounds abuse). | — | Deferred | — |
| F-23 | L | `Dockerfile` | Base image not pinned by digest; builder installs `poetry` by range. | — | Deferred | — |
| F-24 | M | whole bot | No way for a user to delete their stored locations/schedule (privacy). | — | Deferred | — |
| F-25 | M | `bot.py` | No global flood-control for ordinary replies (only scheduler handles `RetryAfter`); needs `python-telegram-bot[rate-limiter]`. | — | Deferred | — |

Not findings (checked): no admin commands exist, so no authorization surface; no webhook mode
(long polling only), so no `secret_token`/HTTPS to verify; no file uploads accepted; no SQL,
`eval`/`exec`, `shell=True`; HTML replies escape user strings with `html.escape`; captions are
already capped at 1024 characters (`caption.py:16`); the container already runs as non-root.

## Deferred items: action required from you

| ID | Why deferred | Exact action |
|---|---|---|
| F-18 | Storage migration needs a product/ops decision and a copy of production data. | Decide SQLite vs JSON; give me a copy of `/data/bot_state.pickle` (or say to build a one-off migration blind); then implement `BasePersistence` + migration. Until then the file is atomic and mode 0600. |
| F-19 | Commit SHAs of third-party actions cannot be resolved from this session (repository scope is limited to this repo). | Run `pin-github-action` / `npx actions-up`, or replace each `uses: x@vN` by `x@<sha> # vN` for `appleboy/telegram-action`, `appleboy/scp-action`, `appleboy/ssh-action`, `docker/*`, `actions/*`; Dependabot (already configured) then keeps them current. Consider `appleboy/telegram-action@master` first: it is the riskiest. |
| F-20 | Pure refactor, touches many test patches (`weather_bot.bot._build_card`). | Approve moving `_build_card/_caption/_card_place` into `cards.py`. |
| F-21 | Removing the cache changes refresh-button behaviour for one-off cities. | Decide: drop the cache (refresh re-geocodes) or scope it per user. |
| F-22 | Needs a measured limit for your VM. | Tell me the VM size, or accept `asyncio.Semaphore(os.cpu_count())` around `render`. |
| F-23 | Digest choice is yours (and Dependabot will bump it). | Provide the desired `python:3.13-slim` digest or approve `docker pull` to read it. |
| F-24 | Product decision (what to delete, retention wording). | Approve a `/forgetme` command that clears `user_data` and removes the schedule. |
| F-25 | Adds a dependency (`aiolimiter`) to the lockfile and changes send timing. | Approve `python-telegram-bot[rate-limiter]` + `AIORateLimiter()` in the builder. |

## Facts (verified by running)

- Baseline on `main`, Python 3.11.17, PTB 22.8:
  `python -m pytest -q` → 139 passed (43 s); `ruff check src tests scripts` and
  `ruff format --check` → clean; `mypy --strict src` → 54 errors in 6 files;
  `bandit -r src` → 17 low, 1 medium (pickle); `pip-audit` → no known vulnerabilities;
  coverage 89 %.
- Final: `pytest -q --cov` → 183 passed, 89.11 % (floor 85 %); `ruff check` + `ruff format --check`
  clean; `mypy` (strict, 27 files) clean; `bandit -q -r src -c pyproject.toml` exit 0;
  `pip-audit --skip-editable` → no known vulnerabilities.
- Secret scan: `git log --all -G'[0-9]{8,10}:[A-Za-z0-9_-]{35}'` → no match; the only deleted
  file with a sensitive-sounding name in history is `.whitesource` (Snyk config). `.env` is
  git-ignored and absent.
- Open-Meteo forecast, Open-Meteo geocoding and Nominatim reverse each returned HTTP 200 with
  no redirect when queried from this environment (basis for `follow_redirects=False`).
- Every Critical/High fix has a test: `test_error_handler.py` (F-01), `test_handler_registration.py`
  (F-03/F-04), `test_updates.py` (F-05), `test_persistence.py` (F-10), `test_ratelimit.py` +
  `test_scheduler.py` + `test_bot.py` (F-17, F-06, F-07), `test_config.py` (F-08/F-09),
  `test_healthcheck.py` (F-12). F-13 is workflow/compose configuration with no unit test.

## Assumptions

- Branch name: the task asks for `chore/review-hardening-<date>`; this session is pinned to
  push to `claude/keen-clarke-po5xv6`, so the work was done on the chore branch locally and is
  pushed to that remote branch.
- The bot runs long polling in a single container (as in `docker-compose.yaml`); per-chat
  limits and per-user locks are in process memory and would not hold across replicas.
- 10 cards/minute/chat is a conservative default chosen by me, not measured.
- No Python-specific skills were available, see header.

## Uncertainties

- Not run: `docker build`, `docker compose up`, the HEALTHCHECK and the deploy workflow (no
  Docker daemon / secrets here). `read_only: true` assumes nothing besides `/data` and `/tmp`
  is written at runtime (`PYTHONDONTWRITEBYTECODE=1` is set); confirm on first deploy.
- `AtomicPicklePersistence` overrides PTB's private `_dump_singlefile`; `python-telegram-bot` is
  pinned `<23`, and a test fails if the override stops being used, but re-check on PTB upgrades.
- The `ssh-action` `envs:` behaviour (variables exported to the remote shell) is taken from its
  documentation, not exercised.
- Behaviour changes (all intended, listed in commit bodies): edited messages/channel posts
  ignored; group free text ignored; `/schedule` private-only; rate limit; refresh failure shown
  as a reply; malformed token / timeout stops startup; aliases sanitised.
