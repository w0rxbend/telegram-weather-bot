from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import TelegramError

from weather_bot import identity


def make_bot(name: str, short: str, desc: str) -> SimpleNamespace:
    bot = SimpleNamespace()
    bot.set_my_commands = AsyncMock()
    bot.get_my_name = AsyncMock(return_value=SimpleNamespace(name=name))
    bot.get_my_short_description = AsyncMock(return_value=SimpleNamespace(short_description=short))
    bot.get_my_description = AsyncMock(return_value=SimpleNamespace(description=desc))
    bot.set_my_name = AsyncMock()
    bot.set_my_short_description = AsyncMock()
    bot.set_my_description = AsyncMock()
    return bot


async def test_sync_updates_only_what_differs() -> None:
    bot = make_bot("Jitsi Meet Link Generator", identity.DEFAULT_SHORT_DESCRIPTION, "old")
    await identity.sync_identity(bot)  # type: ignore[arg-type]
    bot.set_my_commands.assert_awaited_once_with(identity.COMMANDS)
    bot.set_my_name.assert_awaited_once_with(identity.DEFAULT_NAME)
    bot.set_my_description.assert_awaited_once_with(identity.DEFAULT_DESCRIPTION)
    bot.set_my_short_description.assert_not_awaited()


async def test_sync_is_idempotent() -> None:
    bot = make_bot(
        identity.DEFAULT_NAME, identity.DEFAULT_SHORT_DESCRIPTION, identity.DEFAULT_DESCRIPTION
    )
    await identity.sync_identity(bot)  # type: ignore[arg-type]
    bot.set_my_name.assert_not_awaited()
    bot.set_my_description.assert_not_awaited()
    bot.set_my_short_description.assert_not_awaited()


async def test_sync_survives_telegram_errors() -> None:
    bot = make_bot("x", "y", "z")
    bot.set_my_name = AsyncMock(side_effect=TelegramError("Too Many Requests"))
    await identity.sync_identity(bot)  # type: ignore[arg-type]


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BOT_NAME", "My Weather")
    assert identity.desired_identity()[0] == "My Weather"
