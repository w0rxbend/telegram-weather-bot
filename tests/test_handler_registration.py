from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from telegram import Chat, InlineQuery, Location, Message, MessageEntity, Update, User
from telegram.ext import Application, ApplicationBuilder

from weather_bot import bot

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
    assert "on_inline_query" in matching_callbacks(app, inline)
