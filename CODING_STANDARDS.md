# Coding standards

Rules are enforced by tooling where possible. Run everything locally with:

```bash
poetry run ruff check src tests scripts && poetry run ruff format --check src tests scripts
poetry run mypy                                   # strict, config in pyproject.toml
poetry run bandit -q -c pyproject.toml -r src
poetry run pip-audit --skip-editable
poetry run pytest -q
```

CI (`.github/workflows/ci.yml`) runs the same commands; `pre-commit install` runs lint, format, mypy and bandit on commit.

## 1. Layout and layering

- **Handlers → domain modules → storage.** `bot.py` (transport) parses updates and formats replies. Business rules live in `locations.py`, `schedule.py`, `cache.py`, `weather.py`, `geocode.py`. Those modules never import `telegram.ext` handlers. *Why: core logic stays testable without Telegram.*
- Dependencies point one way: `main` → `bot`/`scheduler` → domain → `render`. `scheduler` may import `bot` only under `TYPE_CHECKING` or lazily inside a function.
- No new module-level mutable state. Process-wide objects (HTTP client, caches) go through an accessor (`runtime.http()`, `forecast_cache()`) and are never put in `bot_data`/`user_data`. *Why: those are pickled.*
- Configuration is read once in `config.load_settings()` into a frozen dataclass and validated there. Do not call `os.getenv` elsewhere for new settings.

## 2. Naming and size

- Modules and functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`. Names say what, not how: `due_times`, not `check`.
- Functions ≤ 40 lines and ≤ 3 levels of nesting; one responsibility each. Split before adding a flag parameter.
- No magic numbers or strings: give limits and keys a named constant (`MAX_LOCATIONS`, `CB_REFRESH`).
- No dead code, commented-out code or unused parameters.

## 3. Typing

- `mypy --strict` must pass on `src/`. Every function is fully annotated; no bare `list`/`dict`/`Task`.
- `# type: ignore` needs a specific error code and a reason; prefer `cast` plus a comment when the framework's types are looser than reality.
- Use dataclasses (`frozen=True` by default) for structured data. Use `pathlib`, not `os.path`.
- Python ≥ 3.11 idioms: `X | None`, `match` where it helps, `StrEnum`/`Literal` for closed sets.

## 4. Async rules

Forbidden inside a handler or the scheduler: `time.sleep`, `requests`, synchronous DB/file I/O on large data, CPU-heavy work on the loop.

```python
# bad
png = render_card(forecast, name)
# good: CPU work off the loop, and bounded
async with _render_slots:
    png = await asyncio.to_thread(render_card, forecast, name)
```

- Every `await` on the network has a timeout (the shared `httpx` client sets it).
- Never fire-and-forget: keep a reference to each task and cancel/await it on shutdown (`scheduler.start`/`stop`).
- Code that coalesces work (futures, locks) must release waiters on **every** exit path, including `CancelledError`. *Why: a hung waiter hangs a user forever.*
- State shared between concurrent updates must be mutated without an `await` in the middle of a read-modify-write.

## 5. Errors and logging

- No bare `except:`. `except Exception` is allowed only at a boundary (scheduler tick, error handler) and must log with `log.exception`/`exc_info`. Never `pass`.
- Raise domain errors (`WeatherError`) from domain modules; handlers translate them to a user message.
- Use `logging` with `%s` args, never f-strings; no `print`. Levels: `info` lifecycle, `warning` degraded-but-handled, `error`/`exception` unexpected.
- Never log the bot token, full update payloads or message text. Log user IDs, not names.

## 6. Telegram rules

- **Escaping:** every user- or API-derived string in an HTML message goes through `html.escape`. Plain `reply_text` without `parse_mode` needs no escaping.
- **Limits:** captions ≤ 1024 chars (`CAPTION_LIMIT`), messages ≤ 4096. Truncate in the builder, not in the handler.
- **callback_data** ≤ 64 bytes, treated as hostile: parse with a dedicated function that validates type and range (`_parse_callback` rejects NaN/inf/out-of-range). Always `query.answer()` exactly once.
- **Flood control:** the application uses `AIORateLimiter`; code that sends outside a handler (scheduler) handles `RetryAfter` explicitly.
- **Updates:** only `message` and `callback_query` are requested (`allowed_updates`). Do not add handlers for other types without revisiting abuse paths (live-location edits, channel posts).
- **Authorization:** decide by numeric `user.id`, never by username. There are currently no admin commands; any new one needs a settings-based allowlist of IDs and a test.
- Handlers read `context.user_data` through `_user_data(context)`.

## 7. Security rules

- Secrets only via environment/secret store; `.env` is git-ignored; never baked into images (`docker-compose.yaml` passes `TG_BOT_TOKEN` at runtime).
- Validate every external value at the boundary: text length, numeric ranges, enum membership. Coordinates: finite, |lat| ≤ 90, |lon| ≤ 180.
- No `eval`/`exec`/`shell=True`; no `pickle` for anything but the bot's own state file in `DATA_DIR`. Persisted state is written atomically (`AtomicPicklePersistence`).
- Dependencies: pinned via `poetry.lock`; `pip-audit` must be clean before merge. Containers run as non-root.
- GitHub Actions use `permissions: contents: read` unless a job needs more.

## 8. Testing

- Every bug fix ships a regression test that fails without the fix.
- Domain modules are tested without Telegram; handlers with mocked `Update`/`Bot` (see `tests/test_bot.py`). No test touches the network (the autouse `_stub_http_client` fixture enforces it).
- `asyncio_mode = "auto"`: write `async def test_...` directly.
- New code keeps `pytest`, `ruff`, `mypy` and `bandit` green; do not skip or weaken a test to get green.
