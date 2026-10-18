# Review: hardening of telegram-weather-bot

Scope: whole repository at `cd9e7da` (python-telegram-bot 22.8, polling, `PicklePersistence`,
Poetry, Docker + GitHub Actions deploy). Branch `claude/keen-clarke-091j6t` (see "Facts").

## Executive summary

- **Before:** 133 tests green, ruff green, but no type checking, no dependency audit, 12 known
  vulnerabilities in 4 packages, no rate limiting, a deploy workflow running a mutable
  third-party action (`@master`) with the notify secrets and deploying without tests.
- **After:** 175 tests green (90 % line+branch coverage), ruff / ruff-format / `mypy --strict`
  / bandit / pip-audit all clean; 13 commits; standards and CI enforce them.
- **Top fixed risks:** supply chain (F-02, F-03), per-user flooding of Open-Meteo / Nominatim /
  the renderer (F-06), live-location edits triggering a card per tick (F-10), one bad user
  blocking all scheduled cards (F-14), vulnerable dependencies (F-01).
- **Top remaining risks (deferred, need your decision):** pickle persistence (F-19),
  business logic still lives in `bot.py` (F-20), `drop_pending_updates=True` loses queued
  updates on restart (F-21).
- No secret was found in git history (see Facts). No rotation is required.

## Findings

Severity: Critical / High / Medium / Low. SHA = commit that fixes it.

| ID | Sev | Location | Issue | Fix | Status | SHA |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | High | `poetry.lock` | certifi 2023.5.7, idna 3.4, anyio 3.7.0, python-dotenv 1.0.0 had 12 known vulns (pip-audit) | `poetry update`; dotenv floor `>=1.2.2` | Fixed | ce7a26e |
| F-02 | High | `.github/workflows/docker-ci.yml:19,23,67,..` (before) | `appleboy/telegram-action@master` (mutable ref, receives notify secrets); scp/ssh on floating `@v1` | Pinned to commit SHAs | Fixed | 6e6d056 |
| F-03 | High | `docker-ci.yml` (before: deploy job, `script:`) | Deploy on every push to `main` with no tests; `TG_BOT_TOKEN` expanded into the remote shell script text; no `permissions:` | `test` job + `needs`, token via `envs:`, `permissions: contents: read` | Fixed | 6e6d056 |
| F-04 | Medium | `Dockerfile:11` | `poetry export` included the dev group → pytest, ruff etc. in the runtime image | `--without dev` | Fixed (not built here, see Uncertainties) | cb1893a |
| F-05 | Low | `docker-compose.yaml` | Container kept default Linux capabilities | `cap_drop: [ALL]`, `no-new-privileges` | Fixed | cb1893a |
| F-06 | High | `bot.py` (all expensive handlers) | No per-user limit: every command/callback triggers a forecast fetch + CPU render; one user can exhaust Open-Meteo quota and the thread pool | `ratelimit.Cooldown` + `throttled` (2 s/user) | Fixed | 3df2246 |
| F-07 | Medium | `geocode.py:41`, `main.py` | Nominatim 1 req/s policy not enforced; Bot API 429/RetryAfter not handled | `MinIntervalGate`; `AIORateLimiter(max_retries=3)` | Fixed | 3df2246 |
| F-08 | Medium | `bot.py:_parse_callback` | `float("nan"/"inf")` and out-of-range coordinates from `callback_data` were forwarded to the API | finite + range check | Fixed | b62e074 |
| F-09 | Medium | `bot.py:_slot_arg`, `locations.py:resolve`, `_parse_slot_callback` | `"²".isdigit()` is True but `int("²")` raises → unhandled exception for `/default ²`, `/weather ²`, forged `d\|²` | `isascii() and isdigit()` | Fixed | b62e074 |
| F-10 | High | `bot.py:register_handlers` | Handlers also ran for `edited_message`. A live-location share sends one edit per movement → reverse geocode + forecast + new card per tick; edited commands re-ran | `~filters.UpdateType.EDITED_MESSAGE` on all message handlers | Fixed | f02126b |
| F-11 | Medium | `bot.py:on_error`, `weather.py` | Error handler logged the full `Update` (text, coordinates); `WeatherError`/warnings embedded request URLs with coordinates; failed error notice swallowed silently | log `update_id` only, URL-free reasons, narrow `except TelegramError` + log | Fixed | f02126b |
| F-12 | Low | `config.py`, `main.py` | State pickle and data dir created with default umask; `pickle.load` unannotated | dir 0700, umask 0077, annotated as trusted-local | Fixed (mitigation only; see F-19) | 0ce8d03 |
| F-13 | Low | `config.py:36` | Malformed `HTTP_TIMEOUT` → raw `ValueError`; token never format-checked | `ConfigError`, token regex (value never echoed), positive finite timeout | Fixed | 0ce8d03 |
| F-14 | High | `scheduler.py:tick` (before) | An exception in one user's send aborted the tick for all later users, on every retry until the 10 min grace expired; sends were strictly sequential | per-user isolation via `asyncio.gather` + semaphore (5) | Fixed | 36a7a3a |
| F-15 | Medium | `scheduler.py` (before) | "Sent" marks persisted only after all sends → crash mid-tick re-sends after restart; lazy import of private `bot._…` helpers hid a layering smell | persist before and after sending; public `build_card`, `caption_for`, `card_place`, `card_keyboard` imported at module level | Fixed | 36a7a3a |
| F-16 | Medium | `bot.py` (15 sites) | `assert` used to validate incoming updates (removed under `-O`) | `_require_message/_require_query/_user_data` raise `UnsupportedUpdateError` | Fixed | 4ff3619 |
| F-17 | Low | repo-wide | No type checking; 56 `mypy --strict` errors, 5 blanket `type: ignore`; callbacks on inaccessible (old) messages were dispatched to a type without `reply_text` | typing fixes, `isinstance(message, Message)` guard | Fixed | 4ff3619 |
| F-18 | Low | `bot.py:_send_for_slot` | User argument echoed unbounded; reply could exceed 4096 chars | truncate echo to 40 chars | Fixed | 92f3edf |
| F-19 | Medium | `main.py:51` (`PicklePersistence`) | State is a pickle: whoever can write `/data/bot_state.pickle` gets code execution in the bot; no schema versioning beyond ad-hoc `_migrate` | Mitigated by F-12. Real fix = JSON/SQLite persistence with a migration | **Deferred** | – |
| F-20 | Medium | `bot.py` (~830 lines) | Business rules in handlers (`_apply_schedule`, place cache, slot resolution glue); transport and services not fully separated | Extract `services/` and keep handlers thin | **Deferred** | – |
| F-21 | Low | `main.py:run_polling(drop_pending_updates=True)` | Updates queued while the bot was down (deploy) are discarded, e.g. a location the user just shared | Product decision | **Deferred** | – |
| F-22 | Low | `Dockerfile:1,13` | Base image by tag, not digest; no `HEALTHCHECK` | Pin digest; heartbeat-file health check | **Deferred** | – |
| F-23 | Low | `main.py:LOG_FORMAT` | Plain-text logs, not structured | JSON formatter if you ship logs to an aggregator | **Deferred** | – |
| F-24 | Low | `identity.py:desired_identity` | Reads `os.getenv` directly (hidden input outside `config.py`) | Move into `Settings` | **Deferred** | – |
| T-00 | – | tooling | mypy strict, ruff rule set, bandit, pip-audit, coverage, pre-commit, CI steps, `CODING_STANDARDS.md` | – | Done | 3f98cde |

## Facts (verified by running)

- Baseline (before any change), `poetry install` then:
  `poetry run pytest -q` → 133 passed; `poetry run ruff check src tests scripts` and
  `ruff format --check` → clean (original rule set `E,F,I,B,UP`);
  `poetry run mypy src` (non-strict, default config) → 36 errors in 2 files;
  `mypy --strict src` → 54 errors; `poetry run pip-audit` → 12 vulnerabilities in 4 packages
  (anyio, certifi, idna, python-dotenv); `bandit -r src` → 1 Medium (pickle) + 17 Low (asserts).
- Final, on `HEAD`:
  `poetry run ruff check src tests scripts` ✔, `poetry run ruff format --check src tests scripts` ✔,
  `poetry run mypy` ✔ (22 files, strict), `poetry run bandit -q -c pyproject.toml -r src` ✔,
  `poetry run pip-audit --skip-editable` → "No known vulnerabilities found",
  `poetry run pytest -q --cov` → 175 passed, 90 % total coverage,
  `poetry run pre-commit run --all-files` ✔ (ruff, ruff-format, bandit, mypy).
- Regression tests exist for F-06, F-08, F-09, F-10, F-11, F-13, F-14, F-15, F-16, F-18. For
  F-08/F-09 and F-10/F-11 I confirmed that they fail on the pre-fix source (stash of `src/`);
  for the others I did not run that negative check.
- Secret scan: `git log --all -p` grepped for Telegram token shape `\d{8,10}:[A-Za-z0-9_-]{35}`
  → no matches. `.env` is git-ignored; `.env.example` holds a placeholder only.
- Architecture: polling bot, `ApplicationBuilder` + `PicklePersistence` (single file in
  `DATA_DIR`), `concurrent_updates(True)`; handlers in `bot.py`, a background scheduler task
  (`scheduler.py`), pure logic in `locations.py`, `schedule.py`, `caption.py`, `sun.py`,
  clients `weather.py` (Open-Meteo, retries with backoff, timeouts) and `geocode.py`, Pillow
  rendering in `render/`, process-wide objects in `runtime.py`.
- Authorization: the bot has no admin commands; every user only touches their own `user_data`.
- HTML injection: every user-supplied value placed in an HTML message/caption goes through
  `html.escape`; plain-text replies use no `parse_mode`. `callback_data` is ≤ 20 bytes.

## Assumptions

- The designated branch `claude/keen-clarke-091j6t` was used instead of
  `chore/review-hardening-2026-10-18`, because the session instructions forbid pushing to any
  other branch. Its base equals `main` (`cd9e7da`).
- Single bot instance (polling); no webhook mode, so secret-token verification does not apply.
- The Docker host and Docker Hub account are yours; pinned action SHAs match the tags
  `v1.1.1` / `v1.0.0` / `v1.2.5` as returned by `git ls-remote` at review time.
- A 2 s per-user cooldown is acceptable UX (messages inside it are silently dropped).

## Uncertainties

- The Docker image was **not built** here (no Docker daemon run); `--without dev` and the
  compose hardening are unverified at runtime. `cap_drop: ALL` should be harmless for a
  non-root Python process, but check the first deploy.
- The deploy workflow was not run. The `envs:` hand-over of `TG_BOT_TOKEN` to
  `appleboy/ssh-action` follows its documented interface but is untested.
- `concurrent_updates(True)` plus handlers mutating `user_data` between `await`s could in theory
  interleave for one user (e.g. two quick `/add` flows). The cooldown makes this much less
  likely; I found no concrete corrupting path, but did not prove there is none.
- Existing state files keep their old permissions (umask only affects new files).

## Deferred items: action required from you

| ID | What you need to do |
| --- | --- |
| F-19 | Decide whether to replace `PicklePersistence` (e.g. SQLite/JSON persistence class with a one-off migration of the existing `bot_state.pickle`). Until then keep `/data` writable only by the bot. On the host run once: `chmod 700 <volume path>; chmod 600 <volume path>/bot_state.pickle`. |
| F-20 | Approve a follow-up refactor that moves `_apply_schedule`, place caching and slot resolution into a `services/` package; it touches most of `bot.py` and its tests, so it was not mixed into a hardening change. |
| F-21 | Decide: keep `drop_pending_updates=True` (no stale commands after downtime) or set it to `False` (nothing is lost, old commands replay). |
| F-22 | Provide/approve a base-image digest (`docker buildx imagetools inspect python:3.13-slim`) and whether you want a container health check (a heartbeat file written by the scheduler is the simplest option for a polling bot). |
| F-23 | Say whether logs go to an aggregator; if so, add a JSON formatter. |
| F-24 | Optional: move `BOT_NAME`/descriptions into `Settings` (behaviour-preserving). |
