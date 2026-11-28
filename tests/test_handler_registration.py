from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import (
    CallbackQuery,
    Chat,
    InlineQuery,
    Location,
    Message,
    MessageEntity,
    Update,
    User,
)
from telegram.ext import Application, ApplicationBuilder

from weather_bot import bot
from weather_bot.ratelimit import RateLimiter

USER = User(id=5, first_name="Ann", is_bot=False)


@pytest.fixture
def app() -> Application:
    application = ApplicationBuilder().token("123456:TEST-TOKEN-NOT-REAL").build()
    bot.register_handlers(application)
    return application


def message(chat_type: str = "private", **fields: object) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=5, type=chat_type),
        from_user=USER,
        **fields,  # type: ignore[arg-type]
    )


def matching_callbacks(app: Application, update: Update) -> set[str]:
    names: set[str] = set()
    for handlers in app.handlers.values():
        for handler in handlers:
            if handler.check_update(update):
                names.add(handler.callback.__name__)
    return names


def test_new_location_message_is_handled(app: Application) -> None:
    update = Update(update_id=1, message=message(location=Location(longitude=30.5, latitude=50.4)))
    assert "on_location" in matching_callbacks(app, update)


def test_edited_live_location_is_ignored(app: Application) -> None:
    edited = message(location=Location(longitude=30.5, latitude=50.4))
    assert matching_callbacks(app, Update(update_id=1, edited_message=edited)) == set()


def test_channel_post_is_ignored(app: Application) -> None:
    post = message(chat_type="channel", text="Kyiv")
    assert matching_callbacks(app, Update(update_id=1, channel_post=post)) == set()


def test_edited_command_is_ignored(app: Application) -> None:
    edited = message(text="/weather")
    assert matching_callbacks(app, Update(update_id=1, edited_message=edited)) == set()


def test_new_commands_and_inline_queries_are_routed(app: Application) -> None:
    for command in ("lang", "air", "alerts", "compare", "best", "forget"):
        entity = MessageEntity(MessageEntity.BOT_COMMAND, 0, len(command) + 1)
        command_message = message(text=f"/{command}", entities=[entity])
        command_message.set_bot(SimpleNamespace(username="weatherbot"))  # type: ignore[arg-type]
        update = Update(update_id=1, message=command_message)
        assert matching_callbacks(app, update), command
    inline = Update(update_id=2, inline_query=InlineQuery("1", USER, "Kyiv", ""))
    assert "on_unknown_callback" not in matching_callbacks(app, inline)
    assert "on_inline_query" in matching_callbacks(app, inline)


def first_callback_handler(app: Application, data: str) -> str:
    """The handler PTB runs for a button: the first one in the group that matches."""
    update = Update(update_id=3, callback_query=CallbackQuery("1", USER, "c", data=data))
    for handler in app.handlers[0]:
        if handler.check_update(update):
            return str(handler.callback.__name__)
    return ""


def test_unrecognised_callback_data_is_still_answered(app: Application) -> None:
    """F-50: a button from an older release must not leave its spinner running."""
    assert first_callback_handler(app, "zz|from-an-old-release") == "on_unknown_callback"
    for data, expected in (
        ("r|50.4500|30.5200", "on_card_callback"),
        ("x|0|5", "on_slot_callback"),
        ("sch|morning", "on_schedule_callback"),
        ("forget|yes|5", "on_forget_callback"),
        ("lang|uk", "on_lang_callback"),
    ):
        assert first_callback_handler(app, data) == expected


async def test_help_counts_against_the_per_user_update_budget(
    app: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-57: /help was the one public command outside the flood limit."""
    monkeypatch.setattr(bot, "_update_limiter", RateLimiter(limit=2, window=60))
    entity = MessageEntity(MessageEntity.BOT_COMMAND, 0, len("/help"))
    help_message = message(text="/help", entities=[entity])
    help_message.set_bot(SimpleNamespace(username="weatherbot"))  # type: ignore[arg-type]
    probe = Update(update_id=1, message=help_message)
    (handler,) = [h for h in app.handlers[0] if h.check_update(probe)]

    reply = AsyncMock()
    update = SimpleNamespace(
        effective_user=USER,
        effective_message=SimpleNamespace(reply_text=reply),
        callback_query=None,
    )
    for _ in range(5):
        await handler.callback(update, SimpleNamespace(user_data={}))
    assert reply.await_count == 2
