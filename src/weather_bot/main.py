"""Entry point: ``python -m weather_bot`` or the ``weather-bot`` console script."""

from __future__ import annotations

import asyncio
import logging

import httpx
from telegram.ext import AIORateLimiter, ApplicationBuilder

from weather_bot import scheduler
from weather_bot.bot import make_post_init, post_shutdown, register_handlers
from weather_bot.config import Settings, load_settings
from weather_bot.legacy_state import import_pickle_state, quarantine_corrupt_state
from weather_bot.persistence import SqlitePersistence
from weather_bot.runtime import App

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_API_RETRIES = 3  # Bot API 429s the rate limiter retries before the error reaches a handler
log = logging.getLogger(__name__)


def build_application(settings: Settings, store: SqlitePersistence) -> App:
    """Wire the PTB application; separate from ``start`` so tests can build it without polling."""

    def http_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=settings.http_timeout,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=False,  # none of the three APIs redirect; do not follow surprises
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    bot_post_init = make_post_init(http_factory)
    scheduler_task: list[asyncio.Task[None]] = []

    async def post_init(app: App) -> None:
        await bot_post_init(app)
        scheduler_task.append(scheduler.start(app, heartbeat=settings.heartbeat_file))

    async def post_stop(app: App) -> None:
        await scheduler.stop(scheduler_task.pop() if scheduler_task else None)

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .persistence(store)
        .rate_limiter(AIORateLimiter(max_retries=MAX_API_RETRIES))
        .concurrent_updates(True)
        .post_init(post_init)
        .post_stop(post_stop)
        .post_shutdown(post_shutdown)
        .build()
    )
    register_handlers(application)
    return application


def start() -> None:
    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings()
    store = SqlitePersistence(settings.persistence_file)
    quarantine_corrupt_state(settings.legacy_pickle_file)
    import_pickle_state(settings.legacy_pickle_file, store)

    application = build_application(settings, store)
    log.info("Starting polling; state stored in %s", settings.persistence_file)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start()
