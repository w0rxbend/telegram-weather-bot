# Coding standards

Enforced by `ruff`, `mypy --strict`, `bandit`, `pip-audit` and `pytest` (see
`.pre-commit-config.yaml` and `.github/workflows/ci.yml`). A rule marked **(review)** is not
machine-checked; reviewers enforce it.

## Layout and layering
- `bot.py` is transport only: parse the update, call a service/store function, reply.
  *Why:* logic inside handlers cannot be tested without faking Telegram. **(review)**
- Domain modules (`weather`, `locations`, `schedule`, `sun`, `caption`, `cache`, `geocode`,
  `render/`) must not import `telegram` (except `scheduler`/`bot`/`identity`). **(review)**
- No new module-level mutable state. Shared objects are created in `main.py` and passed in.
  *Why:* hidden globals make tests order-dependent. (`runtime.py` and the forecast cache are
  existing exceptions.)
- Settings are read once in `config.py`, typed, and validated at startup; never `os.getenv`
  inside business code.

## Naming and size
- Names say what a thing is: `due_times`, not `get_stuff`. Constants are `UPPER_SNAKE`, no
  magic numbers inline — name them (`MAX_LOCATIONS`, `INTERVAL`).
- Functions do one thing and fit on a screen (~40 lines); nesting ≤ 3 levels. **(review)**
- No dead code, no commented-out code, no `TODO` without a finding/issue id.

## Typing
- `mypy --strict` must pass; every function is fully annotated. Prefer `dataclass(frozen=True)`
  over dicts for structured data.
- No bare `# type: ignore`; always give the error code and a reason.

## Async rules
- Forbidden inside `async def`: `requests`, `time.sleep`, blocking file/DB I/O, CPU work
  over ~50 ms. Use `httpx.AsyncClient`, `asyncio.sleep`, `asyncio.to_thread`.
- Every `create_task` keeps a reference and has a done-callback or an awaiting owner.
  *Why:* unreferenced tasks are garbage-collected mid-run and swallow exceptions.
- Every outbound HTTP call has a timeout (set on the shared client) and a bounded retry.
- Handlers that mutate `user_data` run serialized per user (see `bot._serialized`).

## Errors and logging
- No bare `except:`; `except Exception` only at a boundary (error handler, scheduler loop)
  and it must log with `log.exception`/`log.warning`. Never `except …: pass`.
- Log with `%s` placeholders, not f-strings.
- **Never log** tokens, message text, full `Update` objects or exact coordinates. Log ids
  (`update_id`, `user_id`) and place names or coordinates rounded to 1 decimal.
  ```python
  log.error("bad update %s", update)            # bad: dumps text + location
  log.error("update %s failed", update.update_id)  # good
  ```

## Telegram rules
- All user text echoed with `parse_mode=HTML` goes through `html.escape`.
- `callback_data` ≤ 64 bytes and is untrusted: parse defensively, range-check numbers
  (latitude −90…90, longitude −180…180), and fall back to "button expired".
- Every callback query handler calls `query.answer()` on every path, including errors.
- Handlers only react to `UpdateType.MESSAGE` (no edited messages, no channel posts).
- Scheduled/bulk sends handle `RetryAfter` (sleep, one retry) and `Forbidden` (unsubscribe).
- Interactive card requests are rate limited per user (`ratelimit.py`).
- Authorization is by numeric user id, never username. (No admin commands exist today.)

## Security
- Secrets come from the environment only; `.env` is git-ignored. Nothing secret in the image,
  workflow scripts, or logs. Pass CI secrets through `envs:`, not string interpolation.
- Validate every user-supplied value: length, charset (strip control characters), range.
- No `pickle` of external data, `eval`, `exec`, `shell=True`.
- Dependencies are pinned by `poetry.lock`; `pip-audit` must be clean before merging.
- The container runs as non-root with a read-only root filesystem.

## Testing
- `pytest` + `pytest-asyncio` (auto mode). Business logic gets unit tests; handlers are tested
  with fake `Update`/`Context` objects.
- Every bug fix ships with a regression test that fails without the fix.
- Network is always mocked (`httpx.MockTransport`); tests must not touch the internet.
