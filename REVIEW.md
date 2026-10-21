# Review: hardening pass (2026-10-18)

## Executive summary
- **Before:** 139 tests green, ruff clean, but `mypy --strict` had 54 errors, `poetry.lock` pinned
  packages with 12 known CVEs (and the Docker image is built from it), full `Update` objects
  (message text, coordinates) were logged, and the state file could be destroyed by a crash.
- **After:** 193 tests green, ruff/format/mypy `--strict`/bandit/pip-audit all clean; CI now runs all
  of them. PII is out of logs, state writes are atomic (0600), per-user locking and rate limiting
  are in place, config is validated at startup, container is read-only with a healthcheck.
- **Top remaining risks:** the SQLite state store (F-20) has not run against production. It has not shipped yet: the Trivy gate was red from #49 on (F-27), so
  the first deploy after F-27 is the F-20 migration; back up the data volume first (see Deferred).
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
| F-27 | Medium | `Dockerfile`, `docker-ci.yml` | The Trivy gate (F-19) failed on every push to main: its five HIGH/CRITICAL hits are the copies vendored inside pip 26.2.1 (certifi 2026.6.17, msgpack 1.1.2, setuptools 70.3.0, urllib3 2.7.0), not our lock. A red gate blocks the image push **and the deploy**, so nothing merged since #49 has shipped | `pip uninstall -y pip` in the runtime stage after the requirements are installed | Fixed (checked in a venv; not run in Actions) | see git log |
| F-28 | Medium | `docker-ci.yml`, `ci.yml` | Deploy ran on any push to main without running the tests; CI tested 3.13 while the image runs 3.14 (#43) | `test` job that `build-and-deploy` needs (3.14); CI matrix 3.13 + 3.14 (suite and mypy pass on 3.14.6) | Fixed (not run in Actions) | see git log |
| F-29 | Low | `geocode.py` | Nominatim's one-request-per-second policy was documented but not enforced | `ratelimit.MinIntervalGate` via `runtime.nominatim_gate()` | Fixed | see git log |
| F-30 | Medium | `main.py` | No Bot API flood control: a 429 reached the handler or the scheduler | `AIORateLimiter(max_retries=3)` (extra `rate-limiter`, adds aiolimiter 1.2.1) | Fixed | see git log |
| F-31 | Medium | `bot.py` `on_card_callback` | A failed refresh answered the callback query twice; Telegram rejects the second answer, so the user saw the generic error | Notice is a chat reply | Fixed | see git log |
| F-32 | Low | `bot.py` `/weather <text>` | Whole argument echoed back; with the prefix it can pass Telegram's 4096 limit | Echo capped at `MAX_QUERY_LENGTH` (80) | Fixed | see git log |
| F-33 | Low | `scheduler.py` `tick` | "Already sent" marks were saved only after sending; a crash mid-tick resent delivered cards | Save before sending and again after | Fixed | see git log |
| F-22 | Medium | `scheduler.py`, `bot.py` | Render per user (not per place) at popular slots; no render semaphore | — | **Deferred** (TODO.md P1/P2) | — |
| F-23 | Low | `bot.py` `/schedule` | Any group member can schedule sends to a group | — | **Deferred** (product decision) | — |
| F-24 | Low | `runtime.py`, `cache.py`, `bot._card_limiter` | Module-level mutable singletons | — | **Accepted** (documented in CODING_STANDARDS.md) | — |
| F-25 | Low | `bot.py` `_remember_place` | Shared `bot_data["places"]` can be primed by any user (stale label only) | — | **Deferred** | — |
| F-34 | Low | `telemetry.py` `event_log` (:97-99, `_record`) | The raw event log (user id, username, event, city) grows without bound and is never pruned; `/export` caps only what is read. Disk growth and open-ended retention of identifiers | Raw rows older than `LOG_RETENTION_DAYS` (90) are deleted, at most once a day; aggregates stay. `/forget` erases a user's rows | Fixed (90 days is my choice; change the constant) | see git log |

Tooling and standards: 174be60, lock sync: see `git log`.

## Deferred — exact action required from you
- **F-20 deploy check:** before the first deploy, back up the data volume; after it, confirm the log line `Imported N users` and that `bot_state.pickle.migrated` exists next to `bot_state.sqlite3`. Rollback: stop the bot, delete the `.sqlite3*` files, rename `.migrated` back to `.pickle`, deploy the previous image.
- **F-22 / F-23:** product/capacity decisions; see `TODO.md`.
- **F-27 / F-28:** after the merge, open the *Docker Image CI* run on `main` and confirm the Trivy step passes. Neither fix has run in Actions; if Trivy still fails, the log names the package.
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

## Follow-up pass (2026-10-21, telemetry)
- Baseline re-run on `main` (584a81d): `pytest -q` 203 passed; ruff check/format, `mypy` (28 files), bandit clean. No new findings.
- Feature requested by the owner: custom usage telemetry (`telemetry.py`, `/stats`, `ADMIN_USER_IDS`). 209 tests pass; ruff, mypy, bandit clean.
- Privacy note: this stores Telegram ids/usernames. Users are told in `/help`; coordinates, message text and chat ids are not stored. Check this against your privacy obligations (GDPR) before enabling for the public.

## Consolidation pass (2026-10-21)
Goal: merge or retire every open PR and unmerged branch, and port only what `main` was still missing.

- Merged #43-#48 (Dependabot: Python 3.14-slim, setup-buildx 4.4.1, setup-qemu 4.4.0, setup-python 7.0.0,
  upload-artifact 7.0.2, build-push-action 7.4.0) after green CI.
- Baseline on `main`: `pytest` 203 passed (3.13 and 3.14.6); ruff, format, mypy (28 files), bandit clean.
  Final: 222 passed on 3.14.6; ruff, format, mypy (28 files), bandit clean; `pip-audit` on the exported lock: no known
  vulnerabilities.
- Method: run each branch's test suite against `main`'s source and read the commits, then port what is missing
  (F-27 to F-33) instead of merging branches that carry competing versions of what #41 and #49 already contain.
  New tests for F-31, F-32, F-33 and the oversize cap were confirmed to fail without the fix.
- Not run: the Docker build and Trivy scan (no daemon here), GitHub Actions, Telegram.

| Branch | PR | Disposition |
|--------|----|-------------|
| `claude/keen-clarke-jfbpll`, `claude/dazzling-heisenberg-r7foh2` | #41, #49 | Merged earlier |
| `claude/determined-davinci-89m7p2`, `ci-updates`, `restyled/ci-updates` | - | Already contained in `main` |
| `claude/keen-clarke-091j6t` (tip 201cea6) | #39 | Ported F-28, F-29, F-30, F-33 and the echo cap (F-32); rest superseded by #41/#49 |
| `claude/keen-clarke-po5xv6` (tip 00ab173) | #40 | Ported F-31 and its routing/error-handler tests; rest superseded. Group-chat scoping of free text and `/schedule` is not ported (F-23, product decision); the implementation is in the closed PR |
| `claude/dazzling-heisenberg-3xhgnc` (tip 6193db0) | #42 | Superseded; its cache-waiter and render-cap fixes were ported earlier (32da5b5) |
| `claude/dazzling-heisenberg-um3y0i` (tip f6f0f47, no PR) | - | Superseded by `httpcap` (F-21, 1 MB); its call-site tests ported with valid padded payloads |
| `snyk-fix-*`, `restyled/snyk-fix-*` | #18-#35 | Retired: they bump Python to 3.13 alpha/beta/rc tags; the image is on 3.14-slim |
| `renovate/configure`, `restyled/renovate/configure` | - | Retired: 2023 Jitsi-bot era (root `main.py`) plus `renovate.json`; Dependabot is the dependency bot |
| `dependabot/*` | #43-#48 | Merged |

Closed PRs keep their commits reachable through `refs/pull/<n>/head` after the branches are deleted; the one branch without
a PR is recoverable from its tip SHA above (`git branch <name> <sha>`) while GitHub still holds the object.

### Merge of the consolidation PR (#53) with `main` after #52
- #53 conflicted with the telemetry PR (#52) in `main.py` and `runtime.py`; both kept (`build_application` from #53, telemetry and
  admin ids wired in `start`).
- Ported from #50: `SqlitePersistence.close()` is now called on shutdown, and the telemetry log is closed with it.
  The rest of #50 (CI matrix 3.13 + 3.14) is already in #53. #51 (matrix 3.11 + 3.14) is folded in as a 3.11/3.13/3.14 matrix.
- `claude/dazzling-heisenberg-um3y0i` is not merged: its response cap (512 KiB, `httpio`) is superseded by `httpcap` (F-21).

## Review pass (2026-10-21, post-consolidation)
- Baseline on `main` (cc25994), Python 3.11.17 venv: `pytest -q` 235 passed; `ruff check src tests scripts` and
  `ruff format --check .` clean; `mypy` (strict) clean on 30 files; `bandit -q -c pyproject.toml -r src` rc 0;
  `pip-audit -r <poetry show pins> --no-deps --disable-pip`: no known vulnerabilities.
- Scope: the code added since the last pass (`telemetry.py`, `/stats`, `/export`, flood control). Admin commands are registered
  only for `ADMIN_USER_IDS` and re-check the numeric id; CSV cells are formula-escaped; HTML output is escaped; SQL is parameterised.
- One new finding, F-34 (Low); fixed in the feature commit below. No Critical/High/Medium findings, so no code changed and no new tests were needed.
- Secret scan of full history (bot-token regex) and of `src` for hard-coded credentials: no matches. No rotation needed.
- Not run: Docker build/Trivy, GitHub Actions, Telegram.
- Branch is `claude/dazzling-heisenberg-4xnydn` (environment-assigned), not `chore/review-hardening-<date>`.

### Features added in the same PR (owner said: decide everything, keep it optimal)
- `/forget` (confirm button): drops the user's persisted state and all telemetry rows (GDPR erasure); `/help` states the 90-day log retention.
- `advice.py`: one caption line with clothing, umbrella (rain >= 50%), SPF (UV >= 6) and wind (gusts >= 30 km/h) tips. Thresholds are constants.
- Final: `pytest -q` 243 passed; ruff, ruff format, mypy (31 files), bandit clean.
- Not done, by choice: localisation, air quality, rain push alerts, inline mode (larger, need product input; listed in `TODO.md`).

### Feature PR (2026-10-21): brainstorm and implementation
The earlier `/forget` + retention + tips commit was pushed to the PR #55 branch *after* #55 was merged, so it never reached `main`; it is part of this PR.
Decisions and rejected ideas: `docs/decisions/0002-feature-brainstorm.md`.
- New: `i18n.py` (en/uk chat text), `airquality.py` + `/air`, `alerts.py` + `/alerts` + `scheduler.alert_tick`, `planner.py` + `/compare` + `/best`, inline mode, all handlers in `handlers_extra.py`.
- Security/robustness notes: every new input is length-checked (`MAX_QUERY_LENGTH`), HTML-escaped, `callback_data` for `/lang` is whitelisted, alert marks are persisted before sending, blocked users are unsubscribed, outbound calls reuse the capped, timeout-bound client.
- Known limits: `/compare` makes up to 3 uncached geocode calls per command; `/best` ignores wind; card PNGs are English only.
- Final: `pytest -q` 287 passed; ruff, ruff format, mypy strict (36 files), bandit clean.
