"""Entry point: ``python -m weather_bot`` or the ``weather-bot`` console script."""

from __future__ import annotations

import logging
import os
import pickle
import time
from pathlib import Path

import httpx
from telegram.ext import AIORateLimiter, ApplicationBuilder, PicklePersistence

from weather_bot import scheduler
from weather_bot.bot import make_post_init, post_shutdown, register_handlers
from weather_bot.config import load_settings

PRIVATE_UMASK = 0o077
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
log = logging.getLogger(__name__)


def quarantine_corrupt_state(path: Path) -> None:
    """Move an unreadable pickle aside so a bad file cannot crash-loop the bot."""
    if not path.exists():
        return
    try:
        with path.open("rb") as fh:
            pickle.load(fh)
    except Exception:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        path.rename(backup)
        log.exception("State file %s was unreadable; moved to %s", path, backup)


def start() -> None:
    os.umask(PRIVATE_UMASK)  # state and quarantined files are readable by this user only
    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings()
    quarantine_corrupt_state(settings.persistence_file)

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
        .persistence(PicklePersistence(filepath=settings.persistence_file))
        .rate_limiter(AIORateLimiter(max_retries=3))
        .concurrent_updates(True)
        .post_init(post_init)
        .post_stop(post_stop)
        .post_shutdown(post_shutdown)
        .build()
    )
    register_handlers(application)
    log.info("Starting polling; state stored in %s", settings.persistence_file)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start()
