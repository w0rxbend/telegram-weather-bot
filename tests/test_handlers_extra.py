from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram.constants import ChatType

from forecast_helpers import set_hour, with_hours
from weather_bot import alerts, handlers_extra
from weather_bot import locations as store
from weather_bot.airquality import AirQuality
from weather_bot.geocode import Place
from weather_bot.weather import Forecast, WeatherError

KYIV = Place("Kyiv, Ukraine", 50.45, 30.52)
LVIV = Place("Lviv, Ukraine", 49.84, 24.03)


def make_update(chat_type: str = ChatType.PRIVATE, code: str = "en", data: str | None = None):
    message = SimpleNamespace(reply_text=AsyncMock(), edit_text=AsyncMock())
    query = SimpleNamespace(data=data, answer=AsyncMock(), message=message)
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=42, type=chat_type),
        effective_user=SimpleNamespace(id=7, language_code=code),
        callback_query=query,
    )


def make_context(args: list[str] | None = None, user_data: dict | None = None):
    return SimpleNamespace(args=args or [], user_data=user_data if user_data is not None else {})


def reply_text(update) -> str:
    return update.effective_message.reply_text.await_args.args[0]


async def test_lang_callback_stores_choice_and_confirms_in_that_language() -> None:
    update, context = make_update(data="lang|uk"), make_context()
    await handlers_extra.on_lang_callback(update, context)
    assert context.user_data["lang"] == "uk"
    update.callback_query.message.edit_text.assert_awaited_once_with("Мову змінено на українську.")


async def test_lang_callback_ignores_junk() -> None:
    update, context = make_update(data="lang|de"), make_context()
    await handlers_extra.on_lang_callback(update, context)
    assert "lang" not in context.user_data
    update.callback_query.answer.assert_awaited_once()


async def test_alerts_toggle_requires_private_chat_and_a_location() -> None:
    group = make_update(chat_type=ChatType.GROUP)
    await handlers_extra.cmd_alerts(group, make_context())
    assert "private chat" in reply_text(group)

    update, context = make_update(), make_context()
    await handlers_extra.cmd_alerts(update, context)
    assert "Save a location first" in reply_text(update)
    assert alerts.chat_id_for(context.user_data) is None

    store.add_location(context.user_data, KYIV)
    await handlers_extra.cmd_alerts(update, context)
    assert alerts.chat_id_for(context.user_data) == 42
    await handlers_extra.cmd_alerts(update, context)  # no argument toggles
    assert alerts.chat_id_for(context.user_data) is None
    await handlers_extra.cmd_alerts(update, make_context(["on"], context.user_data))
    assert alerts.chat_id_for(context.user_data) == 42


async def test_air_reports_quality_for_the_default_location() -> None:
    update, context = make_update(), make_context()
    store.add_location(context.user_data, KYIV)
    with patch.object(
        handlers_extra, "fetch_air_quality", AsyncMock(return_value=AirQuality(18, 4.2, 7.9))
    ):
        await handlers_extra.cmd_air(update, context)
    text = reply_text(update)
    assert "Kyiv, Ukraine" in text and "Good" in text and "AQI 18" in text


async def test_air_failure_and_missing_location_are_explained() -> None:
    update, context = make_update(), make_context()
    await handlers_extra.cmd_air(update, context)
    assert "no saved location" in reply_text(update)
    store.add_location(context.user_data, KYIV)
    with patch.object(
        handlers_extra, "fetch_air_quality", AsyncMock(side_effect=WeatherError("down"))
    ):
        await handlers_extra.cmd_air(update, context)
    assert "not available" in reply_text(update)


async def test_compare_lists_each_city_and_reports_the_unknown_one(forecast: Forecast) -> None:
    places = {"Kyiv": KYIV, "Lviv": LVIV}
    search = AsyncMock(side_effect=lambda client, name, lang: places.get(name))
    update, context = make_update(), make_context(["Kyiv,", "Lviv,", "Nowhere"])
    with (
        patch.object(handlers_extra, "search_place", search),
        patch.object(handlers_extra, "cached_forecast", AsyncMock(return_value=forecast)),
        patch.object(handlers_extra, "_client", lambda context: object()),
    ):
        await handlers_extra.cmd_compare(update, context)
    text = reply_text(update)
    assert "Kyiv, Ukraine" in text and "Lviv, Ukraine" in text
    assert "find “Nowhere”" in text


@pytest.mark.parametrize("args", [[], ["Kyiv"], ["a,", "b,", "c,", "d"], ["Kyiv,", "x"]])
async def test_compare_rejects_bad_input_without_network(args: list[str]) -> None:
    update = make_update()
    with patch.object(handlers_extra, "search_place", AsyncMock()) as search:
        await handlers_extra.cmd_compare(update, make_context(args))
    search.assert_not_awaited()
    assert "Usage: /compare" in reply_text(update)


async def test_best_answers_in_the_users_language(forecast: Forecast) -> None:
    fc = with_hours(forecast, temp=12.0)
    update, context = make_update(code="uk"), make_context(["run"], {"lang_code": "uk"})
    store.add_location(context.user_data, KYIV)
    with (
        patch.object(handlers_extra, "cached_forecast", AsyncMock(return_value=fc)),
        patch.object(handlers_extra, "_client", lambda context: object()),
    ):
        await handlers_extra.cmd_best(update, context)
    text = reply_text(update)
    assert "Найкращий час" in text and "біг" in text and "сьогодні" in text


async def test_best_without_activity_shows_usage() -> None:
    update = make_update()
    await handlers_extra.cmd_best(update, make_context())
    assert "Usage: /best" in reply_text(update)


async def test_best_when_nothing_fits(forecast: Forecast) -> None:
    fc = set_hour(with_hours(forecast, rain=90), 0, precipitation_probability=90)
    update, context = make_update(), make_context(["walk"])
    store.add_location(context.user_data, KYIV)
    with (
        patch.object(handlers_extra, "cached_forecast", AsyncMock(return_value=fc)),
        patch.object(handlers_extra, "_client", lambda context: object()),
    ):
        await handlers_extra.cmd_best(update, context)
    assert "No comfortable" in reply_text(update)


def inline_update(text: str):
    inline = SimpleNamespace(query=text, answer=AsyncMock())
    return SimpleNamespace(
        inline_query=inline, effective_user=SimpleNamespace(id=7, language_code="en")
    )


async def test_inline_query_offers_one_result(forecast: Forecast) -> None:
    update = inline_update("Kyiv")
    with (
        patch.object(handlers_extra, "search_place", AsyncMock(return_value=KYIV)),
        patch.object(handlers_extra, "cached_forecast", AsyncMock(return_value=forecast)),
        patch.object(handlers_extra, "_client", lambda context: object()),
    ):
        await handlers_extra.on_inline_query(update, make_context())
    results = update.inline_query.answer.await_args.args[0]
    assert len(results) == 1 and "Kyiv, Ukraine" in results[0].title
    assert update.inline_query.answer.await_args.kwargs["is_personal"] is True


@pytest.mark.parametrize("text", ["", "k", "x" * 200])
async def test_inline_query_with_bad_text_answers_empty_without_network(text: str) -> None:
    update = inline_update(text)
    with patch.object(handlers_extra, "search_place", AsyncMock()) as search:
        await handlers_extra.on_inline_query(update, make_context())
    search.assert_not_awaited()
    assert update.inline_query.answer.await_args.args[0] == []


async def test_inline_query_unknown_city_answers_empty() -> None:
    update = inline_update("Nowhere")
    with (
        patch.object(handlers_extra, "search_place", AsyncMock(return_value=None)),
        patch.object(handlers_extra, "_client", lambda context: object()),
    ):
        await handlers_extra.on_inline_query(update, make_context())
    assert update.inline_query.answer.await_args.args[0] == []
