# Coding standards

Rules for this repository. Each rule has a one-line statement and a short *why*.
Checks marked **[CI]** are enforced by `.github/workflows/ci.yml` and pre-commit.

Run everything locally:

```bash
poetry install
poetry run ruff check src tests scripts && poetry run ruff format --check src tests scripts
poetry run mypy
poetry run bandit -q -r src -c pyproject.toml
poetry run pip-audit --skip-editable
poetry run pytest -q --cov
```

## 1. Layout and layering

```
transport   bot.py, scheduler.py, main.py     Telegram objects live here, nowhere else
services    weather.py, cache.py, geocode.py, caption.py, schedule.py, locations.py, sun.py
rendering   render/                           pure functions: data in, PNG bytes out
config      config.py                         the only module that reads os.environ
```

- Dependencies point downwards only: transport → services → rendering. **Why:** services stay
  testable without Telegram.
- Services and rendering must not import `telegram`. **Why:** core logic is framework-free.
- Handlers parse input, call a service, format the reply. No business rules in handlers.
- Process-wide singletons (`runtime.http`, `cache._cache`) are accessed only through their
  accessor functions, never imported as variables. **Why:** tests replace them in one place.
- Configuration is read once at startup into a frozen dataclass and validated there. **Why:**
  a bad value fails at boot, not at the first request.

## 2. Naming, size, style

- `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants; no abbreviations
  except `lat`, `lon`, `tz`, `fc`. **[ruff N via review]**
- A function does one thing and fits on a screen (≤ 40 lines, ≤ 3 nesting levels).
- No magic values: a literal that is used twice or carries meaning gets a named constant.
- No dead code, no commented-out code, no `TODO` without an issue reference.
- Line length 100, formatted by `ruff format`. **[CI]**
- Public functions have a docstring only when the name cannot say it all; comments explain
  *why*, not *what*.

## 3. Typing

- `mypy --strict` passes with no `ignore_errors`. **[CI]**
- Every function is fully annotated; avoid `Any` (allowed only at framework boundaries,
  with a comment).
- Value objects are frozen `@dataclass`es. Never pass loose `dict`s between layers.
- `# type: ignore[code]` needs the specific code and a reason on the same line.
- Replace `assert x is not None` in handlers with an explicit guard (`if x is None: return`).
  **Why:** `assert` is stripped by `python -O` and Telegram updates really do arrive
  without `effective_message`. **[ruff S101]**

## 4. Async rules

Forbidden inside `async def`:

| Forbidden | Use instead |
|---|---|
| `requests`, `urllib`, sync `httpx` | the shared `httpx.AsyncClient` |
| `time.sleep` | `await asyncio.sleep` |
| Pillow / CPU work over ~20 ms | `await asyncio.to_thread(...)` |
| `open()` / `Path.read_*` on the hot path | `to_thread` or load at startup |
| `asyncio.create_task(...)` without keeping the reference | store the task, add a done-callback that logs |
| bare `except:` / swallowing `CancelledError` | catch specific errors; re-raise `CancelledError` |

- Every network call has a timeout (set on the client) and, for idempotent GETs, bounded
  retries with backoff.
- Updates of the same user are processed one at a time (`UserSerialUpdateProcessor`).
  **Why:** handlers mutate `user_data` with read-modify-write sequences.
- Shutdown cancels and awaits every background task and closes the HTTP client.

## 5. Errors and logging

- Catch the narrowest exception that you can handle. `except Exception` is allowed only at a
  loop or handler boundary, with `log.exception`, and a `# noqa: BLE001 - reason`.
- User-facing errors are short and actionable; internal details go to the log only.
- Logging uses `%s` lazy formatting and a module-level `log = logging.getLogger(__name__)`.
- **Never log**: the bot token, `Update` objects, message text, exact coordinates, or
  user names. Log `update_id`, `user_id` and the exception. **Why:** logs are shipped and
  retained; they must not become a location history.
- `print` is forbidden in `src/`. **[ruff T20]**

## 6. Telegram rules

- Register a global error handler; it must log without PII and never raise.
- Every `CallbackQuery` is answered exactly once on every code path (a second answer raises).
- `callback_data` ≤ 64 bytes and is untrusted input: parse strictly, range-check numbers
  (latitude −90…90, longitude −180…180), reject `nan`/`inf`.
- Any user-controlled string inserted into a `parse_mode=HTML` message goes through
  `html.escape`. Prefer plain text when no formatting is needed.
- Respect limits: message ≤ 4096 chars, caption ≤ 1024 chars. Truncate before sending.
- Handlers that make sense only for user messages are bound to `filters.UpdateType.MESSAGE`
  (not edited messages, not channel posts). **Why:** live-location edits fire every few
  seconds.
- Free-text handlers are restricted to private chats; commands work everywhere.
- Heavy actions (card render + upload) are rate limited per user.
- Scheduled sends isolate failures per user and treat `Forbidden` as "user left": delete the
  schedule. `RetryAfter` is honoured (sleep, retry once).
- Authorization is by numeric user id checked server-side; never trust `@username`. (The bot
  has no admin commands today; add any with an id allow-list from `config.py`.)

## 7. Security rules

- Secrets only via environment variables or a secret store. Never in code, images, logs, CI
  scripts or git. `.env` is git-ignored; `.env.example` holds placeholders only.
- CI/CD: workflows declare least-privilege `permissions:`; secrets are passed through
  `env:`/`envs:`, never interpolated into shell script text; third-party actions are pinned
  to a version or commit SHA (Dependabot keeps them current).
- Validate every external input (user text, callback data, API responses) at the boundary:
  type, length, range, character set.
- No `eval`/`exec`/`shell=True`/`yaml.load`. `pickle` only for files this process wrote
  itself, inside the data volume. **[bandit]**
- Dependencies are locked (`poetry.lock`) and audited (`pip-audit`) in CI; fix or document
  every finding.
- Containers run as non-root, with a read-only root filesystem and no extra capabilities.

## 8. Testing

- `pytest` + `pytest-asyncio` (auto mode). Tests never touch the network or the real Telegram
  API; handlers get a mocked `Update`/`Context`. **[CI]**
- Every bug fix and every Critical/High finding comes with a test that fails without it.
- Business logic (services, parsing, scheduling) is tested directly, without Telegram mocks.
- Coverage floor 85% (`--cov`, enforced). New code must not lower it.
- No sleeping tests: inject clocks (`now=`) or patch `asyncio.sleep`.
