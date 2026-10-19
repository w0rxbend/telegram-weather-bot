"""Entry point: ``python -m weather_bot`` or the ``weather-bot`` console script."""

from __future__ import annotations

import logging
import pickle
import time
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import AIORateLimiter, ApplicationBuilder

from weather_bot import scheduler
from weather_bot.bot import make_post_init, post_shutdown, register_handlers
from weather_bot.cache import forecast_cache
from weather_bot.config import load_settings
from weather_bot.persistence import AtomicPicklePersistence

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
log = logging.getLogger(__name__)


def quarantine_corrupt_state(path: Path) -> None:
    """Move an unreadable pickle aside so a bad file cannot crash-loop the bot."""
    if not path.exists():
        return
    try:
        with path.open("rb") as fh:
            # Trusted input: our own file in DATA_DIR, which PTB unpickles the same way anyway.
            pickle.load(fh)  # noqa: S301  # nosec B301
    except Exception as exc:  # noqa: BLE001 - any unpickling failure counts
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        path.rename(backup)
        log.error("State file %s was unreadable (%s); moved to %s", path, exc, backup)


def start() -> None:
    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings()
    quarantine_corrupt_state(settings.persistence_file)
    forecast_cache().ttl = settings.forecast_cache_ttl

    def http_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )

    bot_post_init = make_post_init(http_factory)
    scheduler_task: list = []

    async def post_init(app) -> None:
        await bot_post_init(app)
        scheduler_task.append(scheduler.start(app))

    async def post_stop(app) -> None:
        await scheduler.stop(scheduler_task.pop() if scheduler_task else None)

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .persistence(AtomicPicklePersistence(filepath=settings.persistence_file))
        .rate_limiter(AIORateLimiter(max_retries=3))
        .concurrent_updates(True)
        .post_init(post_init)
        .post_stop(post_stop)
        .post_shutdown(post_shutdown)
        .build()
    )
    register_handlers(application)
    log.info("Starting polling; state stored in %s", settings.persistence_file)
    application.run_polling(
        drop_pending_updates=True,
        # No edited messages (live-location edits would re-render cards), no channel posts.
        allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
    )


if __name__ == "__main__":
    start()
