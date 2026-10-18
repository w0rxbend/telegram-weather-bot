from __future__ import annotations

from datetime import UTC, datetime

import pytest
from telegram import Chat, Location, Message, MessageEntity, Update, User
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


def test_free_text_in_group_is_ignored_but_private_is_handled(app: Application) -> None:
    group = Update(update_id=1, message=message(chat_type="group", text="Kyiv"))
    private = Update(update_id=2, message=message(text="Kyiv"))
    assert "on_text" not in matching_callbacks(app, group)
    assert "on_text" in matching_callbacks(app, private)


def test_edited_command_is_ignored(app: Application) -> None:
    edited = message(text="/weather")
    assert matching_callbacks(app, Update(update_id=1, edited_message=edited)) == set()


def test_schedule_is_private_only(app: Application, monkeypatch: pytest.MonkeyPatch) -> None:
    # CommandHandler compares against the bot's username, which normally needs a network call.
    monkeypatch.setattr(type(app.bot), "username", property(lambda _self: "testbot"))
    entity = [MessageEntity(type="bot_command", offset=0, length=9)]
    private = Update(update_id=1, message=message(text="/schedule", entities=entity))
    group = Update(
        update_id=2, message=message(chat_type="group", text="/schedule", entities=entity)
    )
    for update in (private, group):
        assert update.message is not None
        update.message.set_bot(app.bot)
    assert matching_callbacks(app, private) == {"cmd_schedule"}
    assert matching_callbacks(app, group) == {"cmd_schedule_private_only"}
