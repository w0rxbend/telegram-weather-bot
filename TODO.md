# TODO — performance, security and robustness review

Reviewed on 2026-10-18 against the code as of the forecast-cache commit. Each item says
**why** it matters, **how** to do it, and how to **verify** it. Priorities:

- **P1** – do before the bot gets more than a handful of users or any public exposure.
- **P2** – worthwhile within the next few iterations.
- **P3** – nice to have.

Already handled (kept here for context): HTTP client is no longer stored in persisted
`bot_data` (it broke pickling and crashed startup); a corrupt state file is moved aside instead of
crash-looping; forecasts are cached per place/units/hour with request coalescing and a stale
fallback; one user's failed scheduled send no longer aborts the tick.

Handled by PR #41 (merged 2026-10-19, details in `REVIEW.md`): atomic 0600 state-file writes
(`persistence.py`), `RetryAfter` retry in the scheduler, per-user locking and a 10 cards/minute
rate limit, callback/slot input validation, edited-message and channel-post filtering, PII-free
logging (`privacy.py`), validated config, lock refresh for known CVEs, `TG_BOT_TOKEN` passed to
the deploy via `envs:`, `permissions: contents: read`, Dependabot, container healthcheck
(`health.py`) with `read_only` / `cap_drop` / `no-new-privileges`, mypy `--strict`, bandit and
pip-audit in CI, `CODING_STANDARDS.md`. Ported from PR #42: cache waiters released when a fetch is
cancelled; render concurrency capped at the CPU count.

Items below that are now done are marked **[done]** in their heading; the rest stay open.

Later passes are recorded in `REVIEW.md` (F-18 to F-33); headings marked **[done]** below were
brought in line with the code on 2026-10-21.

---

## Robustness

### P1 · Atomic writes for the persistence file **[done in #41; rolling backups still open]**
**Why.** `PicklePersistence._dump_singlefile` opens the file with `"wb"` (truncating it) and
then pickles. A crash, OOM kill or container stop between those two steps leaves an empty or
partial file. The quarantine guard in `main.py` prevents a crash loop, but all user state is
still lost.

**How.** Subclass `PicklePersistence` and override `_dump_singlefile` to write to
`bot_state.pickle.tmp` and `os.replace()` it over the real file (rename is atomic on the same
filesystem). Keep the last N good files as rolling backups (`bot_state.pickle.1`, `.2`) so a
logical corruption can be rolled back by hand. Files live in `DATA_DIR`.

**Verify.** Unit test: patch `pickle.dump` to raise midway and assert the original file is
intact. Kill the container with `docker kill` during load and confirm state survives.

### P1 · Move state from pickle to SQLite **[done: `SqlitePersistence` + one-off pickle import, see docs/decisions/0001-state-storage.md]**
**Why.** A single pickle rewrites *all* users on every flush (default every 60 s when anything
changed), loads everything into memory, and cannot be inspected or migrated safely. Pickle also
executes arbitrary code on load if the file is ever tampered with.

**How.** Implement `BasePersistence` on top of `aiosqlite` (tables: `users(user_id, json)`,
`bot(key, json)`), or use a plain repository module (`storage.py`) and drop PTB persistence
entirely; the data model is already dict/JSON-friendly (`locations.py`, `schedule.py`,
`units`). Add a one-off migration that reads an existing pickle and writes the rows. Keep
`DATA_DIR` as the location so the Docker volume stays the same.

**Verify.** Round-trip tests per module; run the migration against a copy of the production
file (`docker cp`).

### P1 · Telegram flood control for scheduled sends **[done: RetryAfter retry in #41, `AIORateLimiter` in the 2026-10-21 consolidation pass]**
**Why.** At a popular slot (07:30) the scheduler sends one photo per user back-to-back.
Telegram allows ~30 messages/second overall and 1 message/second per chat; over that it
returns `RetryAfter`, which is currently just logged, so the user misses the card.

**How.** Add `python-telegram-bot[rate-limiter]` and `.rate_limiter(AIORateLimiter())` to the
`ApplicationBuilder` so every send is throttled and retried transparently. In the scheduler
`_send`, catch `telegram.error.RetryAfter` explicitly and sleep `exc.retry_after` before one
retry, as a belt-and-braces measure.

**Verify.** Unit test `_send` with a `RetryAfter(1)` then success; load test with 100 fake users
due at the same minute against a mocked bot and assert all 100 are sent.

### P1 · Render once per place for scheduled sends
**Why.** Users in the same city at the same slot each trigger a full ~1 s render (Pillow at 2×,
PNG optimisation). The forecast cache removes the API call but not the CPU. 300 users in
Kyiv at 07:30 = 5 minutes of rendering, longer than the 10-minute grace window on a small VM.

**How.** In `scheduler.tick`, group due users by `(cache key, units, place display name)`;
render once per group; send the first photo as bytes and reuse the returned
`message.photo[-1].file_id` for the rest (`send_photo(photo=file_id)` is instant, no upload).
Add a short-lived render cache (`(forecast key, kind, name, HH:MM) -> png`) in `cache.py`
for the interactive path too: pressing 🔄 twice within a minute should not re-render.

**Verify.** Test that `_build_card` is called once for N users sharing a place; measure
`tick` duration with 100 users before/after.

### P2 · Protect the event loop from render CPU **[semaphore done; JPEG / lower scale still open]**
**Why.** `render_card` runs in `asyncio.to_thread`, but Pillow holds the GIL for much of the
work, so a burst of renders still makes handlers sluggish. There is no cap on concurrent
renders.

**How.** Wrap render calls in an `asyncio.Semaphore(os.cpu_count())`; optionally move
rendering to a `ProcessPoolExecutor` (icons and fonts are `lru_cache`d per process, so warm
the pool at startup). Lower the cost per render: `SCALE = 2` → consider 1.5× with
`Image.Resampling.LANCZOS`, and save as JPEG quality 88 instead of `PNG optimize=True`
(Telegram re-encodes photos to JPEG anyway; the PNG step is wasted CPU and 3× the upload).

**Verify.** `python -m timeit` on `render_card` before/after; eyeball `docs/preview-*.png` for
regressions; keep the PNG path for the README previews.

### P2 · Per-user and global rate limiting of interactive commands **[done in #41]**
**Why.** Any user can spam `/weather` or the refresh button; each hit costs a render and an
upload. Nothing stops a hostile user from pinning the CPU.

**How.** Keep a token bucket per user in memory (e.g. 10 cards/minute, 100/hour); reply with a
short "slow down" message when exceeded. Answer callback queries with `show_alert=False` text
instead of rendering. Combine with the render semaphore above.

**Verify.** Test: 11 rapid calls → 10 photos, 1 text reply.

### P2 · Health check and self-monitoring **[done in #41; metrics still open]**
**Why.** A hung polling loop or a scheduler task that died silently looks identical to
"no messages". Docker's `restart: unless-stopped` only restarts on process exit.

**How.** Write a heartbeat file (`DATA_DIR/heartbeat`) from the scheduler tick and from the
PTB job that polls updates; add a `HEALTHCHECK` to the Dockerfile that fails when the file
is older than 2 minutes. Optionally expose `/healthz` on a tiny aiohttp server for an
external uptime monitor. Log a WARNING if a scheduler tick takes longer than the interval.

**Verify.** `docker inspect --format '{{.State.Health.Status}}'`; kill the scheduler task in a
test and assert the healthcheck turns unhealthy.

### P2 · Sequential processing per user **[done in #41]**
**Why.** `concurrent_updates(True)` lets two updates from the same user run in parallel.
Both mutate `user_data` (slot add/remove, schedule set), so a fast double-tap can interleave
and, in the worst case, remove the wrong slot.

**How.** Either drop `concurrent_updates` (simplest; renders are already off-loop) or keep a
`dict[user_id, asyncio.Lock]` and acquire it in a small decorator around the handlers that
write `user_data`.

**Verify.** Test that two concurrent `/remove 1` calls on a two-slot user leave one slot.

### P3 · Scheduled sends in group chats
**Why.** A schedule set inside a group sends a card to the group every slot; any member can
set one, and `user_data` is per user, so several members can create several schedules for the
same group.

**How.** Restrict `/schedule` to private chats, or require group admin status
(`get_chat_member(...).status in {"administrator", "creator"}`) and store group schedules in
`chat_data` so there is one per group.

### P3 · Observability
**Why.** There are no counters for cache hits, renders, sends, or API failures; the only
signal is the log.

**How.** Expose `cache.hits/misses`, render count/time, scheduled-send outcomes as Prometheus
metrics on the health endpoint, or log a one-line stats summary every 10 minutes. Consider
Sentry (`sentry-sdk`) for exception reports; redact `update` payloads (see security below).

---

## Security

### P1 · Pin GitHub Actions and stop interpolating secrets into shell scripts **[done: secrets via envs in #41, SHA pins F-18]**
**Why.** `appleboy/telegram-action@master` and `appleboy/ssh-action@v1` / `scp-action@v1`
track mutable refs; a compromised upstream commit runs with your Docker Hub and SSH
secrets. The deploy step writes `export TG_BOT_TOKEN=${{ secrets.TG_BOT_TOKEN }}` into a
shell script that is sent over SSH, so the token is visible in the remote shell's history and
process list and would break on special characters.

**How.** Pin every action to a commit SHA (`uses: appleboy/ssh-action@<sha> # v1.2.x`) and let
Dependabot bump them (`.github/dependabot.yml` with `package-ecosystem: github-actions` and
`pip`). Pass secrets to ssh-action via its `envs:` input instead of the script body, and
write the token into a `.env` file on the server with `umask 077` that `docker compose`
reads (`env_file`). Add `permissions: contents: read` at the top of both workflows.

**Verify.** `grep -n "@master\|@v1$" .github/workflows/*.yml` returns nothing; the deploy log
shows no `export TG_BOT_TOKEN`.

### P1 · Keep personal data out of logs **[done in #41]**
**Why.** `on_error` logs the whole `Update` (user id, name, message text, shared coordinates)
at ERROR level; warnings in `bot.py` and `scheduler.py` include `Place(...)` with exact
coordinates. Logs end up in `docker logs` and any log shipper.

**How.** In `on_error`, log `update.update_id`, `effective_user.id` and the exception only.
Replace `%s` of `Place` objects with a rounded `(lat, lon)` to 1 decimal or the place name.
Set `logging.getLogger("telegram").setLevel(logging.WARNING)` so request bodies never appear
at INFO.

**Verify.** Trigger an exception in a test handler and assert the captured log has no
coordinates or message text.

### P2 · Treat the persistence file as sensitive
**Why.** It contains every user's saved coordinates and aliases ("home", "office") in clear
text in a Docker volume, and pickle unpickles arbitrary objects.

**How.** After moving to SQLite (above), set file mode 600; back it up encrypted
(`age`/`gpg`) if backups are taken; add a `/forgetme` command that deletes the user's row
(`user_data.clear()`), which also serves as a GDPR-style erasure path; mention retention in
the bot description.

### P2 · Validate and bound user-controlled input everywhere **[alias normalisation done in #41; places cache scoping still open]**
**Why.** Most inputs are bounded already (city query 2–80 chars, alias ≤ 30, ≤ 24 schedule
times, ≤ 10 slots). Two gaps: `/rename` and `/add` aliases are stored verbatim and rendered
on the card with Pillow, where very long or RTL/combining strings could overflow the header
(the header truncates by width, so this is cosmetic); and the shared `bot_data["places"]`
name cache is keyed by coordinates with names from the geocoder, so a user can prime an
entry for coordinates another user later shares. The name comes from Nominatim, not the
user, so the impact is a stale label, not injection.

**How.** Normalise aliases (`unicodedata.normalize("NFKC")`, strip control characters,
collapse whitespace). Scope the places cache by user (`user_data`) or drop it: saved slots
already carry their names, and one-off cities can be re-geocoded on refresh.

### P2 · Dependency and image hygiene **[done: pip-audit, Dependabot, read_only in #41; Trivy gate F-19, unblocked in F-27]**
**Why.** The image is rebuilt from `python:3.13-slim` on every push, but nothing re-pins or
audits dependencies, and there is no SBOM or vulnerability scan since `.whitesource` was
removed.

**How.** Add `pip-audit` (or `poetry run pip-audit`) and `ruff` to `ci.yml`; add Trivy
(`aquasecurity/trivy-action`) against the built image in `docker-ci.yml` and fail on
HIGH/CRITICAL; enable Dependabot for pip (weekly). Run the container with
`read_only: true` and `tmpfs: /tmp` in `docker-compose.yaml` (only `/data` needs writes),
and `cap_drop: [ALL]`.

### P3 · Outbound request hardening **[done: redirects off + connection cap in #41, 1 MB response cap F-21]**
**Why.** The bot calls three public APIs with a 15 s timeout, follows redirects, and has no
response size limit. A misbehaving endpoint could hold connections or return a huge body.

**How.** Set `httpx.Limits(max_connections=20)`, disable `follow_redirects` (none of the APIs
need it), and read responses with a size guard (`len(response.content) < 2 MB`). Consider an
allow-list of hosts in the client's transport.

---

## Performance

### P2 · Cheaper and faster images
Covered under "Protect the event loop": JPEG output, lower supersampling, render cache,
`file_id` reuse. Expected effect: ~3× less CPU per card and ~3× smaller uploads.

### P2 · Forecast cache sizing and warm-up
**Why.** A `Forecast` holds 168 hourly points plus daily data (~40–60 KB as Python objects);
`MAX_ENTRIES = 5000` could reach ~300 MB on a busy bot, which is a lot for a small VM.

**How.** Lower `MAX_ENTRIES` to ~1000, or store only the 48 hourly points the renderer needs
(`next_hours(24)` plus the current day). Warm the cache for every place that has a schedule
one minute before its slot, so the scheduled minute does only renders and sends.

**Verify.** `tracemalloc` snapshot after filling 1000 entries from the fixture.

### P3 · Scheduler scan cost
**Why.** Every 30 s the tick iterates all users and parses each schedule. Fine up to tens of
thousands of users; beyond that it adds latency and GC pressure.

**How.** Keep an in-memory index `{(tz, "HH:MM"): set(user_ids)}` rebuilt when schedules
change, and only look at the entries for the current local minute. Tick on the minute
boundary instead of every 30 s.

### P3 · Startup time
**Why.** Fonts and icons are built lazily; the first card after a deploy takes ~2 s longer.

**How.** Call `fonts.font(...)` for the used sizes and `icons.icon(...)` for all kinds in
`post_init`.

---

## Product / UX gaps worth tracking

- **Localisation. [done for chat text: `i18n.py`, `/lang`; card images stay English]** Captions, menus and the card text are English only; `language_code` is
  already used for geocoding. Add `gettext` catalogs for the caption and menus first (cheap),
  then card labels.
- **Sun-card schedule.** `/schedule` sends only the weather card. Add a per-schedule card
  kind, and a "sunset reminder" preset that fires at `sunset − 30 min` computed from the
  cached forecast.
- **Weather alerts. [rain alerts done: `alerts.py`; frost/wind thresholds still open]** Open-Meteo has no warnings feed; consider a daily "rain expected"
  push based on `precipitation_probability_max ≥ 70`.
- **Telegram Desktop setup.** Typed city names work, but the welcome text could show the
  city option more prominently when `message.from_user` has no location capability.
- **Tests for the rendering layout.** Current tests only assert image size. Add golden-image
  tests with a perceptual hash (`imagehash`) so layout regressions are caught in CI.
