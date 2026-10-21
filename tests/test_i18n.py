from __future__ import annotations

import string
from datetime import date

from weather_bot import i18n
from weather_bot.weather import WMO_DESCRIPTIONS


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_string_exists_in_both_languages_with_the_same_placeholders() -> None:
    for key, texts in i18n.STRINGS.items():
        assert set(texts) == set(i18n.SUPPORTED), key
        assert _fields(texts["en"]) == _fields(texts["uk"]), key


def test_ukrainian_weather_descriptions_cover_every_wmo_code() -> None:
    assert set(i18n.WMO_UK) == set(WMO_DESCRIPTIONS)


def test_language_comes_from_choice_then_telegram_code() -> None:
    assert i18n.resolve_lang({}, "uk-UA") == "uk"
    assert i18n.resolve_lang({}, "de") == "en"
    assert i18n.resolve_lang({}, None) == "en"
    assert i18n.resolve_lang({i18n.KEY_LANG: "en"}, "uk") == "en"
    assert i18n.resolve_lang({i18n.KEY_LANG: "xx"}, "uk") == "uk"  # junk in state is ignored


def test_weekday_and_description_are_localised() -> None:
    assert i18n.weekday("uk", date(2026, 10, 19)) == "Пн"
    assert i18n.weekday("en", date(2026, 10, 19)) == "Mon"
    assert i18n.describe_weather("uk", 63, "Rain") == "Дощ"
    assert i18n.describe_weather("en", 63, "Rain") == "Rain"
    assert i18n.describe_weather("uk", 12345, "?") == "Невідомо"
