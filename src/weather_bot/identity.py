"""Keep the bot's public identity (name, descriptions, commands) in sync on startup.

Telegram lets a bot set its own name and descriptions through the Bot API, so the Jitsi-era
branding is replaced automatically on deploy. The profile picture can only be changed in
@BotFather (``/setuserpic``); ``docs/avatar.png`` is a ready-made image for that.
"""

from __future__ import annotations

import logging
import os

from telegram import Bot, BotCommand
from telegram.error import TelegramError

log = logging.getLogger(__name__)

DEFAULT_NAME = "Weather Card Bot"
DEFAULT_SHORT_DESCRIPTION = (
    "Styled weather infographics for your location. Share it once, then /weather any time."
)
DEFAULT_DESCRIPTION = (
    "Share your location once and I'll turn it into a beautiful weather card: current "
    "conditions, a 24-hour temperature curve with rain chances and a 7-day outlook.\n\n"
    "/weather – fresh card for your location\n"
    "/setup – change location\n"
    "/units – °C / °F\n\n"
    "Weather data by Open-Meteo.com"
)

COMMANDS = [
    BotCommand("weather", "Fresh weather infographic"),
    BotCommand("setup", "Change your saved location"),
    BotCommand("units", "Switch °C / °F"),
    BotCommand("help", "How to use the bot"),
]


def desired_identity() -> tuple[str, str, str]:
    return (
        os.getenv("BOT_NAME", DEFAULT_NAME),
        os.getenv("BOT_SHORT_DESCRIPTION", DEFAULT_SHORT_DESCRIPTION),
        os.getenv("BOT_DESCRIPTION", DEFAULT_DESCRIPTION),
    )


async def sync_identity(bot: Bot) -> None:
    """Apply name/descriptions/commands only when they differ; never fail startup."""
    name, short_description, description = desired_identity()
    try:
        await bot.set_my_commands(COMMANDS)
        if (await bot.get_my_short_description()).short_description != short_description:
            await bot.set_my_short_description(short_description)
            log.info("Updated bot short description")
        if (await bot.get_my_description()).description != description:
            await bot.set_my_description(description)
            log.info("Updated bot description")
        # Name changes are rate limited by Telegram, so only touch it when needed.
        if (await bot.get_my_name()).name != name:
            await bot.set_my_name(name)
            log.info("Updated bot name to %r", name)
    except TelegramError as exc:
        log.warning("Could not sync bot identity: %s", exc)
