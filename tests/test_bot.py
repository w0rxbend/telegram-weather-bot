from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weather_bot import bot
from weather_bot import locations as store
from weather_bot.geocode import Place
from weather_bot.weather import Forecast

KYIV = Place(name="Kyiv, Ukraine", latitude=50.45, longitude=30.52)
LVIV = Place(name="Lviv, Ukraine", latitude=49.84, longitude=24.03)


def make_context(user_data: dict | None = None, args: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        user_data=user_data if user_data is not None else {},
        bot_data={},
        args=args or [],
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


def patched(forecast: Forecast):
    return (
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_card", return_value=b"\x89PNGfake"),
    )


def test_place_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "MAX_CACHED_PLACES", 3)
    ctx = make_context()
    for i in range(5):
        bot._remember_place(ctx, Place(name=f"p{i}", latitude=i, longitude=i))
    places = ctx.bot_data["places"]
    assert len(places) == 3
    assert "4.0000,4.0000" in places
    assert "0.0000,0.0000" not in places


def test_recall_prefers_saved_slot_label() -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV, "home")
    assert bot._recall_place(ctx, 50.45, 30.52).name == "home · Kyiv, Ukraine"
    assert bot._recall_place(ctx, 1.0, 2.0).name == "1.000, 2.000"


def test_keyboard_and_callback_parsing() -> None:
    kb = bot._keyboard(KYIV, "metric")
    refresh, units = kb.inline_keyboard[0]
    assert refresh.callback_data == "r|50.4500|30.5200"
    assert units.text == "Show in °F"
    assert kb.inline_keyboard[1][0].callback_data == "s|50.4500|30.5200"
    assert kb.inline_keyboard[1][1].callback_data == "l|0"
    assert bot._parse_callback(refresh.callback_data) == ("r", 50.45, 30.52)
    assert bot._parse_callback("garbage") is None
    assert bot._parse_slot_callback("d|2") == ("d", 2)
    assert bot._parse_slot_callback(None) is None


async def test_start_without_location_asks_for_it() -> None:
    ctx = make_context()
    update = make_update()
    await bot.cmd_start(update, ctx)
    assert ctx.user_data["awaiting_location"] == {"alias": None}
    kwargs = update.effective_message.reply_text.await_args.kwargs
    assert kwargs["reply_markup"] is bot.LOCATION_KEYBOARD
    assert "Ann" in update.effective_message.reply_text.await_args.args[0]


async def test_weather_without_location_prompts_setup() -> None:
    ctx = make_context()
    update = make_update()
    await bot.cmd_weather(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    update.effective_message.reply_photo.assert_not_awaited()


async def test_weather_uses_default_and_slot_argument(forecast: Forecast) -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    store.add_location(ctx.user_data, LVIV, "home")
    update = make_update()
    p1, p2 = patched(forecast)
    with p1 as fetch, p2:
        await bot.cmd_weather(update, ctx)
        assert fetch.await_args.args[1:3] == (50.45, 30.52)
        call = update.effective_message.reply_photo.await_args.kwargs
        assert call["photo"] == b"\x89PNGfake"
        assert "Kyiv, Ukraine" in call["caption"]
        assert "16°C" in call["caption"]

        ctx.args = ["home"]
        await bot.cmd_weather(update, ctx)
        assert fetch.await_args.args[1:3] == (49.84, 24.03)
        assert (
            "home · Lviv, Ukraine"
            in update.effective_message.reply_photo.await_args.kwargs["caption"]
        )

        ctx.args = ["7"]
        await bot.cmd_weather(update, ctx)
    assert "No saved location matches" in update.effective_message.reply_text.await_args.args[0]


async def test_location_message_adds_slot_and_replies(forecast: Forecast) -> None:
    ctx = make_context({"awaiting_location": {"alias": "home"}})
    update = make_update(location=SimpleNamespace(latitude=50.45, longitude=30.52))
    p1, p2 = patched(forecast)
    with patch.object(bot, "reverse_geocode", AsyncMock(return_value=KYIV)), p1, p2:
        await bot.on_location(update, ctx)
    locs = store.list_locations(ctx.user_data)
    assert len(locs) == 1 and locs[0].alias == "home" and locs[0].is_default
    assert "awaiting_location" not in ctx.user_data
    intro = update.effective_message.reply_text.await_args.args[0]
    assert "Saved slot <b>1</b>" in intro and "(default)" in intro
    update.effective_message.reply_photo.assert_awaited_once()


async def test_second_location_is_not_default(forecast: Forecast) -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    ctx.args = ["office"]
    update = make_update()
    await bot.cmd_add(update, ctx)
    assert ctx.user_data["awaiting_location"] == {"alias": "office"}
    update = make_update(text="Lviv")
    p1, p2 = patched(forecast)
    with patch.object(bot, "search_place", AsyncMock(return_value=LVIV)), p1, p2:
        await bot.on_text(update, ctx)
    locs = store.list_locations(ctx.user_data)
    assert [loc.label for loc in locs] == ["Kyiv, Ukraine", "office"]
    assert store.get_default(ctx.user_data).place == KYIV
    assert "/weather 2" in update.effective_message.reply_text.await_args.args[0]


async def test_text_after_setup_is_one_off(forecast: Forecast) -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    update = make_update(text="Paris")
    paris = Place(name="Paris, France", latitude=48.85, longitude=2.35)
    p1, p2 = patched(forecast)
    with patch.object(bot, "search_place", AsyncMock(return_value=paris)), p1, p2:
        await bot.on_text(update, ctx)
    assert len(store.list_locations(ctx.user_data)) == 1  # unchanged
    assert bot._recall_place(ctx, 48.85, 2.35).name == "Paris, France"
    update.effective_message.reply_photo.assert_awaited_once()


async def test_unknown_city() -> None:
    ctx = make_context()
    update = make_update(text="qwertyuiop")
    with patch.object(bot, "search_place", AsyncMock(return_value=None)):
        await bot.on_text(update, ctx)
    assert "couldn't find" in update.effective_message.reply_text.await_args.args[0]


async def test_locations_list_default_remove_rename() -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    store.add_location(ctx.user_data, LVIV)
    update = make_update()
    await bot.cmd_locations(update, ctx)
    text = update.effective_message.reply_text.await_args.args[0]
    assert "1. <b>Kyiv, Ukraine</b> ⭐" in text and "2. <b>Lviv, Ukraine</b>" in text
    keyboard = update.effective_message.reply_text.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[1][0].callback_data == "w|1"

    ctx.args = ["2"]
    await bot.cmd_default(update, ctx)
    assert store.get_default(ctx.user_data).place == LVIV

    ctx.args = ["2", "home", "sweet"]
    await bot.cmd_rename(update, ctx)
    assert store.list_locations(ctx.user_data)[1].alias == "home sweet"

    ctx.args = ["1"]
    await bot.cmd_remove(update, ctx)
    assert [loc.place for loc in store.list_locations(ctx.user_data)] == [LVIV]

    ctx.args = []
    await bot.cmd_default(update, ctx)
    assert "Usage" in update.effective_message.reply_text.await_args.args[0]


def make_query(data: str) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_media = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.reply_text = AsyncMock()
    query.message.reply_photo = AsyncMock()
    query.message.chat.send_action = AsyncMock()
    return query


async def test_refresh_callback_edits_media(forecast: Forecast) -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    query = make_query("r|50.4500|30.5200")
    p1, p2 = patched(forecast)
    with p1, p2:
        await bot.on_card_callback(SimpleNamespace(callback_query=query), ctx)
    query.edit_message_media.assert_awaited_once()
    media = query.edit_message_media.await_args.kwargs["media"]
    assert "Kyiv, Ukraine" in media.caption


async def test_units_callback_toggles_units(forecast: Forecast) -> None:
    ctx = make_context()
    query = make_query("u|50.4500|30.5200")
    fetch = AsyncMock(return_value=forecast)
    with (
        patch.object(bot, "fetch_forecast", fetch),
        patch.object(bot, "render_card", return_value=b"png"),
    ):
        await bot.on_card_callback(SimpleNamespace(callback_query=query), ctx)
    assert ctx.user_data["units"] == "imperial"
    assert fetch.await_args.args[-1] == "imperial"


async def test_slot_callbacks(forecast: Forecast) -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    store.add_location(ctx.user_data, LVIV)

    query = make_query("w|1")
    p1, p2 = patched(forecast)
    with p1 as fetch, p2:
        await bot.on_slot_callback(SimpleNamespace(callback_query=query), ctx)
    assert fetch.await_args.args[1:3] == (49.84, 24.03)
    query.message.reply_photo.assert_awaited_once()

    query = make_query("d|1")
    await bot.on_slot_callback(SimpleNamespace(callback_query=query), ctx)
    assert store.get_default(ctx.user_data).place == LVIV
    query.edit_message_text.assert_awaited_once()

    query = make_query("x|0")
    await bot.on_slot_callback(SimpleNamespace(callback_query=query), ctx)
    assert [loc.place for loc in store.list_locations(ctx.user_data)] == [LVIV]

    query = make_query("l|0")
    await bot.on_slot_callback(SimpleNamespace(callback_query=query), ctx)
    query.message.reply_text.assert_awaited_once()


async def test_sun_command_and_switch_buttons(forecast: Forecast) -> None:
    ctx = make_context()
    store.add_location(ctx.user_data, KYIV)
    update = make_update()
    with (
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_sun_card", return_value=b"sunpng") as render,
    ):
        await bot.cmd_sun(update, ctx)
    render.assert_called_once()
    call = update.effective_message.reply_photo.await_args.kwargs
    assert call["photo"] == b"sunpng"
    assert "🌅 Sunrise" in call["caption"]
    buttons = call["reply_markup"].inline_keyboard
    assert buttons[0][0].callback_data == "s|50.4500|30.5200"  # refresh keeps the sun card
    assert buttons[0][1].callback_data == "r|50.4500|30.5200"  # switch to weather card

    # weather card carries a button to the sun card; pressing it edits in place
    assert bot._keyboard(KYIV, "metric").inline_keyboard[1][0].callback_data == "s|50.4500|30.5200"
    query = make_query("s|50.4500|30.5200")
    with (
        patch.object(bot, "fetch_forecast", AsyncMock(return_value=forecast)),
        patch.object(bot, "render_sun_card", return_value=b"sunpng"),
    ):
        await bot.on_card_callback(SimpleNamespace(callback_query=query), ctx)
    media = query.edit_message_media.await_args.kwargs["media"]
    assert "🌅 Sunrise" in media.caption
