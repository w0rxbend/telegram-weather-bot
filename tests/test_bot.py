from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weather_bot import bot
from weather_bot.geocode import Place
from weather_bot.weather import Forecast

KYIV = Place(name="Kyiv, Ukraine", latitude=50.45, longitude=30.52)


def make_context(user_data: dict | None = None, bot_data: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        user_data=user_data if user_data is not None else {},
        bot_data=bot_data or {"http": object()},
    )


def make_update(
    text: str | None = None, location: object | None = None, first_name: str = "Ann"
) -> SimpleNamespace:
    message = MagicMock()
    message.text = text
    message.location = location
    message.reply_text = AsyncMock()
    message.reply_photo = AsyncMock()
    message.chat.send_action = AsyncMock()
    user = SimpleNamespace(first_name=first_name, language_code="en")
    return SimpleNamespace(effective_message=message, effective_user=user)


def test_place_round_trip() -> None:
    ctx = make_context({"awaiting_location": True})
    bot._save_place(ctx, KYIV)
    assert bot._saved_place(ctx) == KYIV
    assert "awaiting_location" not in ctx.user_data
    assert bot._recall_place(ctx, 50.45, 30.52).name == "Kyiv, Ukraine"
    assert bot._recall_place(ctx, 1.0, 2.0).name == "1.000, 2.000"


def test_place_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "MAX_CACHED_PLACES", 3)
    ctx = make_context()
    for i in range(5):
        bot._remember_place(ctx, Place(name=f"p{i}", latitude=i, longitude=i))
    places = ctx.bot_data["places"]
    assert len(places) == 3
    assert "4.0000,4.0000" in places
    assert "0.0000,0.0000" not in places


def test_keyboard_and_callback_parsing() -> None:
    kb = bot._keyboard(KYIV, "metric")
    refresh, units = kb.inline_keyboard[0]
    assert refresh.callback_data == "r|50.4500|30.5200"
    assert units.text == "Show in °F"
    assert bot._parse_callback(refresh.callback_data) == ("r", 50.45, 30.52)
    assert bot._parse_callback("garbage") is None
    assert bot._parse_callback(None) is None


async def test_start_without_location_asks_for_it() -> None:
    ctx = make_context()
    update = make_update()
    await bot.cmd_start(update, ctx)
    assert ctx.user_data["awaiting_location"] is True
    kwargs = update.effective_message.reply_text.await_args.kwargs
    assert kwargs["reply_markup"] is bot.LOCATION_KEYBOARD
    assert "Ann" in update.effective_message.reply_text.await_args.args[0]


async def test_weather_without_location_prompts_setup() -> None:
    ctx = make_context()
    update = make_update()
    await bot.cmd_weather(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    update.effective_message.reply_photo.assert_not_awaited()


async def test_weather_sends_photo(forecast: Forecast) -> None:
    ctx = make_context()
    bot._save_place(ctx, KYIV)
    update = make_update()
    with (
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_card", return_value=b"\x89PNGfake"),
    ):
        await bot.cmd_weather(update, ctx)
    call = update.effective_message.reply_photo.await_args.kwargs
    assert call["photo"] == b"\x89PNGfake"
    assert "Kyiv, Ukraine" in call["caption"]
    assert "16°C" in call["caption"]


async def test_location_message_saves_and_replies(forecast: Forecast) -> None:
    ctx = make_context({"awaiting_location": True})
    update = make_update(location=SimpleNamespace(latitude=50.45, longitude=30.52))
    with (
        patch.object(bot, "reverse_geocode", AsyncMock(return_value=KYIV)),
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_card", return_value=b"png"),
    ):
        await bot.on_location(update, ctx)
    assert bot._saved_place(ctx) == KYIV
    # keyboard removal message, then the photo
    update.effective_message.reply_text.assert_awaited_once()
    update.effective_message.reply_photo.assert_awaited_once()


async def test_text_during_setup_saves_city(forecast: Forecast) -> None:
    ctx = make_context({"awaiting_location": True})
    update = make_update(text="Lviv")
    lviv = Place(name="Lviv, Ukraine", latitude=49.84, longitude=24.03)
    with (
        patch.object(bot, "search_place", AsyncMock(return_value=lviv)),
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_card", return_value=b"png"),
    ):
        await bot.on_text(update, ctx)
    assert bot._saved_place(ctx) == lviv


async def test_text_after_setup_is_one_off(forecast: Forecast) -> None:
    ctx = make_context()
    bot._save_place(ctx, KYIV)
    update = make_update(text="Paris")
    paris = Place(name="Paris, France", latitude=48.85, longitude=2.35)
    with (
        patch.object(bot, "search_place", AsyncMock(return_value=paris)),
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_card", return_value=b"png"),
    ):
        await bot.on_text(update, ctx)
    assert bot._saved_place(ctx) == KYIV  # unchanged
    assert bot._recall_place(ctx, 48.85, 2.35).name == "Paris, France"
    update.effective_message.reply_photo.assert_awaited_once()


async def test_unknown_city() -> None:
    ctx = make_context()
    update = make_update(text="qwertyuiop")
    with patch.object(bot, "search_place", AsyncMock(return_value=None)):
        await bot.on_text(update, ctx)
    assert "couldn't find" in update.effective_message.reply_text.await_args.args[0]


async def test_refresh_callback_edits_media(forecast: Forecast) -> None:
    ctx = make_context()
    bot._save_place(ctx, KYIV)
    query = MagicMock()
    query.data = "r|50.4500|30.5200"
    query.answer = AsyncMock()
    query.edit_message_media = AsyncMock()
    update = SimpleNamespace(callback_query=query)
    with (
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_card", return_value=b"png"),
    ):
        await bot.on_callback(update, ctx)
    query.edit_message_media.assert_awaited_once()
    media = query.edit_message_media.await_args.kwargs["media"]
    assert "Kyiv, Ukraine" in media.caption


async def test_units_callback_toggles_units(forecast: Forecast) -> None:
    ctx = make_context()
    query = MagicMock()
    query.data = "u|50.4500|30.5200"
    query.answer = AsyncMock()
    query.edit_message_media = AsyncMock()
    update = SimpleNamespace(callback_query=query)
    fetch = AsyncMock(return_value=forecast)
    with (
        patch.object(bot, "fetch_forecast", fetch),
        patch.object(bot, "render_card", return_value=b"png"),
    ):
        await bot.on_callback(update, ctx)
    assert ctx.user_data["units"] == "imperial"
    assert fetch.await_args.args[-1] == "imperial"
