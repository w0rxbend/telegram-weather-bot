# Coding standards

These rules are enforced by `ruff`, `mypy --strict`, `bandit`, `pip-audit` and `pytest` (see
`pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`). A rule marked
**(review)** cannot be checked by a tool and is checked in code review.

Run everything locally:

```bash
poetry run ruff check src tests scripts && poetry run ruff format --check src tests scripts
poetry run mypy
poetry run bandit -q -c pyproject.toml -r src
poetry run pip-audit --skip-editable
poetry run pytest -q --cov
```

## 1. Layout and layering

| Layer | Modules | May import | Must not |
| --- | --- | --- | --- |
| Transport | `bot.py`, `scheduler.py`, `main.py` | everything below | hold business rules |
| Services / domain | `locations.py`, `schedule.py`, `caption.py`, `cards.py`, `ratelimit.py` | domain, `weather`, `geocode` | import `telegram.ext` handlers |
| Clients | `weather.py`, `geocode.py` | `httpx` | know about Telegram |
| Rendering | `render/` | `weather` data classes | do I/O or network |
| Config | `config.py` | stdlib, `dotenv` | be read from anywhere except `main.py` |

- Dependencies point downwards only; no import cycles and no function-level imports to
  hide a cycle. *Why: a lazy import is a cycle you stopped seeing.*
- Handlers parse the update, call a service, format the reply. Decisions (limits, matching,
  scheduling maths) live in services and are unit-tested without Telegram. **(review)**
- Configuration is read once in `config.load_settings()` into a frozen dataclass and passed
  down. No `os.getenv` outside `config.py`. *Why: hidden inputs break testability.*

## 2. Naming, size, style

- Modules and functions are `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`.
  Names say what, not how (`due_times`, not `check`).
- A function does one thing; ≤ 50 statements, ≤ 12 branches, ≤ 7 arguments (ruff `PL`).
  Drawing code in `render/` is exempt.
- No magic values in logic: give limits and keys a named constant
  (`MAX_LOCATIONS`, `CALLBACK_DATA_LIMIT`).
- No dead code, no commented-out code, no `print` (use `logging`), no `TODO` without an issue.
- Comments explain *why*; code explains *what*.

## 3. Typing

- `mypy --strict` is green. Every function has full annotations (ruff `ANN`).
- Use `dataclass(frozen=True)` (or pydantic) for data crossing a function boundary, not bare
  `dict`s. Persisted `user_data` dicts are accessed only through `locations.py` / `schedule.py`.
- `# type: ignore[code]` needs the exact error code and a reason. Never bare.
- Never use `assert` for runtime checks of external input: asserts vanish under `python -O`.
  Raise or reply instead.

```python
# bad
assert message is not None
# good
message = require_message(update)
```

## 4. Async rules

Forbidden inside handlers and any coroutine (ruff `ASYNC` catches most):

- `requests`, `time.sleep`, blocking file or DB I/O. Use `httpx.AsyncClient`, `asyncio.sleep`.
- CPU-heavy work (Pillow rendering) on the event loop: use `asyncio.to_thread`.
- `asyncio.create_task(...)` without keeping a reference *and* handling its exceptions.
- Unbounded fan-out: concurrent work to external services goes through a `Semaphore`.
- Catching `asyncio.CancelledError` without re-raising.

Every long-lived task has an owner that cancels and awaits it on shutdown.
Every network call has an explicit timeout (the shared `httpx.AsyncClient` carries it).

## 5. Errors and logging

- No bare `except:`; `except Exception` only at a boundary (global error handler, scheduler
  loop) and it must log with `log.exception`. Ruff `BLE`/`TRY` enforce this.
- Catch the narrowest exception that you can handle; convert third-party errors to a domain
  error at the client boundary (`WeatherError`).
- Never swallow silently (`except …: pass`). If ignoring is intended, use
  `contextlib.suppress` and say why.
- Log with `%s` placeholders, never f-strings. Levels: `debug` internals, `info` lifecycle,
  `warning` recoverable external failure, `error`/`exception` bugs.
- **Never log**: the bot token, full `Update` objects, message text, coordinates or names of
  users. Log ids (`update_id`) and error types. *Why: logs are copied around; PII is not ours
  to spread.*

## 6. Telegram rules

- Every user-supplied string put in a message with `parse_mode=HTML` goes through
  `html.escape`. Messages without `parse_mode` are sent as plain text. **(review)**
- Replies and captions respect Telegram limits: text 4096, caption 1024 (`caption.CAPTION_LIMIT`).
- `callback_data` ≤ 64 bytes, short fixed-grammar, parsed strictly and range-checked
  (finite, lat ∈ [-90, 90], lon ∈ [-180, 180]); a client can send anything. Never put
  secrets or user text in it.
- Every `CallbackQuery` is answered exactly once on every path (success, error, expired).
- Handlers that trigger external calls are rate limited per user (`ratelimit.py`). The bot is
  built with `AIORateLimiter` so Bot API 429s are retried instead of dropped.
- Authorization (if admin commands appear) compares numeric `user.id` against a configured
  allow-list, never usernames.
- Handle `Forbidden` (user blocked the bot) by dropping that user's scheduled work.
- Commands ignore edited messages (`~filters.UpdateType.EDITED_MESSAGE`).
- Persisted state (`PicklePersistence`) is trusted local storage: the data directory is
  private (0700) and never user-writable. Do not load pickles from anywhere else.

## 7. Security rules

- Secrets only from the environment / `.env` (git-ignored). Never in code, tests, logs,
  Docker layers or CI scripts printed to logs. A leaked secret is rotated, not just removed.
- Validate every external value at the boundary: text length, numeric ranges, slot indices,
  `isdigit()` must be `isascii() and isdigit()` before `int()` (`"²".isdigit()` is true).
- No `eval`/`exec`/`pickle` of anything not written by this process, no `shell=True`,
  no string-built SQL.
- Third-party GitHub Actions are pinned to a version tag (or SHA) — never `@master`.
  Workflows declare least-privilege `permissions:`.
- Dependencies: pinned via `poetry.lock`; `pip-audit` must be clean on `main`. Upgrades go
  through `poetry update <pkg>`.
- Containers run as non-root, with no secrets baked into layers, only runtime dependencies
  installed (`poetry export --without dev`).

## 8. Testing

- `pytest` + `pytest-asyncio` (auto mode). Tests run without network or a real Telegram:
  handlers are called with mocked `Update`/`Context`, HTTP via `httpx.MockTransport`.
- Business logic (`locations`, `schedule`, `ratelimit`, parsing, caption) has unit tests for
  success, boundary and malformed input.
- Every bug fix and every Critical/High security fix ships with a regression test that fails
  without the fix.
- Test names describe behaviour: `test_rejects_non_finite_coordinates`.
- Coverage is reported in CI; do not lower it in a PR. **(review)**

## 9. Git and review

- Conventional Commits (`fix(security): …`, `refactor(handlers): …`, `chore(tooling): …`).
- One logical change per commit; behaviour changes are called out in the commit body.
- Never commit `.env`, state files (`*.pickle`), or local artifacts.
- CI must be green before merge; do not skip or disable a test to get there.
