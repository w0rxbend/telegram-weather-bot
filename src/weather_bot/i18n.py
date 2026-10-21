"""Text for the two supported languages (English, Ukrainian).

The language comes from the user's ``/lang`` choice, else Telegram's ``language_code``.
Only chat text is translated; the text drawn inside the PNG cards stays English.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from datetime import date
from typing import Any, Literal, get_args

Lang = Literal["en", "uk"]
SUPPORTED: tuple[str, ...] = get_args(Lang)
DEFAULT_LANG: Lang = "en"
KEY_LANG = "lang"

_WEEKDAYS: dict[Lang, tuple[str, ...]] = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "uk": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"),
}

WMO_UK: dict[int, str] = {
    0: "Ясно",
    1: "Переважно ясно",
    2: "Мінлива хмарність",
    3: "Похмуро",
    45: "Туман",
    48: "Паморозний туман",
    51: "Легка мряка",
    53: "Мряка",
    55: "Густа мряка",
    56: "Паморозна мряка",
    57: "Паморозна мряка",
    61: "Невеликий дощ",
    63: "Дощ",
    65: "Сильний дощ",
    66: "Крижаний дощ",
    67: "Крижаний дощ",
    71: "Невеликий сніг",
    73: "Сніг",
    75: "Сильний сніг",
    77: "Снігова крупа",
    80: "Невеликі зливи",
    81: "Зливи",
    82: "Сильні зливи",
    85: "Сніговий дощ",
    86: "Сильний сніговий дощ",
    95: "Гроза",
    96: "Гроза з градом",
    99: "Гроза з сильним градом",
}

STRINGS: dict[str, dict[Lang, str]] = {
    "today": {"en": "Today", "uk": "Сьогодні"},
    "next_days": {"en": "Next days", "uk": "Наступні дні"},
    "feels_like": {"en": "feels like", "uk": "відчувається як"},
    "updated": {"en": "Updated", "uk": "Оновлено"},
    "sunrise": {"en": "Sunrise", "uk": "Схід"},
    "sunset": {"en": "Sunset", "uk": "Захід"},
    "daylight": {"en": "Daylight", "uk": "Світловий день"},
    "solar_noon": {"en": "Solar noon", "uk": "Сонячний полудень"},
    "golden_hour": {"en": "Golden hour", "uk": "Золота година"},
    "coat_winter": {"en": "Winter coat", "uk": "Зимова куртка"},
    "coat_warm": {"en": "Warm jacket", "uk": "Тепла куртка"},
    "coat_light": {"en": "Light jacket", "uk": "Легка куртка"},
    "sleeves": {"en": "Long sleeves", "uk": "Довгий рукав"},
    "tshirt": {"en": "T-shirt weather", "uk": "Футболка"},
    "umbrella": {"en": "Umbrella", "uk": "Парасолька"},
    "spf": {"en": "SPF", "uk": "SPF"},
    "windy": {"en": "Windy", "uk": "Вітряно"},
    "lang_set": {
        "en": "Language set to English.",
        "uk": "Мову змінено на українську.",
    },
    "lang_prompt": {"en": "Choose a language:", "uk": "Оберіть мову:"},
    "welcome": {
        "en": (
            "Hi {name}! I turn your location into a weather infographic.\n\n"
            "Tap <b>📍 Share my location</b> below, or type a city name. "
            "After that, send /weather any time for a fresh picture."
        ),
        "uk": (
            "Привіт, {name}! Я перетворюю вашу геолокацію на погодну інфографіку.\n\n"
            "Натисніть <b>📍 Поділитися локацією</b> нижче або напишіть назву міста. "
            "Потім надсилайте /weather, коли потрібна свіжа картинка."
        ),
    },
    "cant_find": {
        "en": "I couldn't find “{query}”. Try another spelling.",
        "uk": "Не знайшов «{query}». Спробуйте інше написання.",
    },
    "weather_down": {
        "en": "I couldn't reach the weather service right now. Please try again in a minute.",
        "uk": "Зараз не вдається отримати погоду. Спробуйте через хвилину.",
    },
    "air_title": {"en": "Air quality", "uk": "Якість повітря"},
    "air_unavailable": {
        "en": "Air quality data is not available for this place.",
        "uk": "Для цього місця немає даних про якість повітря.",
    },
    "aqi_good": {"en": "Good", "uk": "Добра"},
    "aqi_fair": {"en": "Fair", "uk": "Задовільна"},
    "aqi_moderate": {"en": "Moderate", "uk": "Помірна"},
    "aqi_poor": {"en": "Poor", "uk": "Погана"},
    "aqi_very_poor": {"en": "Very poor", "uk": "Дуже погана"},
    "aqi_extreme": {"en": "Extremely poor", "uk": "Небезпечна"},
    "alerts_on": {
        "en": "☔ Rain alerts are on. I'll message you when rain is likely in the next hours "
        "at your default location.",
        "uk": "☔ Сповіщення про дощ увімкнено. Напишу, коли в найближчі години за вашою "
        "локацією за замовчуванням очікується дощ.",
    },
    "alerts_off": {"en": "Rain alerts are off.", "uk": "Сповіщення про дощ вимкнено."},
    "alerts_need_location": {
        "en": "Save a location first (/add or type a city), then turn alerts on.",
        "uk": "Спершу збережіть локацію (/add або назва міста), потім увімкніть сповіщення.",
    },
    "rain_alert": {
        "en": "☔ <b>Rain likely around {time}</b> in {place} ({probability}%). Take an umbrella.",
        "uk": "☔ <b>Ймовірний дощ близько {time}</b>, {place} ({probability}%). "
        "Візьміть парасольку.",
    },
    "compare_usage": {
        "en": "Usage: /compare Kyiv, Lviv (2–3 cities). If a name contains a comma, separate the "
        "cities with “vs” or “|”: /compare Paris, France vs London",
        "uk": "Використання: /compare Київ, Львів (2–3 міста). Якщо в назві є кома, розділяйте "
        "міста «vs» або «|»: /compare Paris, France vs London",
    },
    "compare_title": {"en": "Weather comparison", "uk": "Порівняння погоди"},
    "best_usage": {
        "en": "Usage: /best run, /best bike or /best walk",
        "uk": "Використання: /best run, /best bike або /best walk (біг, велосипед, прогулянка)",
    },
    "best_none": {
        "en": "No comfortable, dry daylight window in the next 24 hours.",
        "uk": "У найближчі 24 години немає комфортного сухого вікна при денному світлі.",
    },
    "best_result": {
        "en": "{emoji} Best time for a {activity}: <b>{day} {start}–{end}</b>\n"
        "{temp} · ☔ {rain}% in {place}",
        "uk": "{emoji} Найкращий час ({activity}): <b>{day} {start}–{end}</b>\n"
        "{temp} · ☔ {rain}% у {place}",
    },
    "alerts_private_only": {
        "en": "Rain alerts work in a private chat with me.",
        "uk": "Сповіщення про дощ працюють лише в особистому чаті зі мною.",
    },
    "day_today": {"en": "today", "uk": "сьогодні"},
    "day_tomorrow": {"en": "tomorrow", "uk": "завтра"},
    "no_location": {
        "en": "You have no saved location yet. Share one with /add or type a city name.",
        "uk": "У вас ще немає збереженої локації. Надішліть її через /add або напишіть місто.",
    },
}

ACTIVITY_NAMES: dict[str, dict[Lang, str]] = {
    "run": {"en": "run", "uk": "біг"},
    "bike": {"en": "bike ride", "uk": "велопрогулянка"},
    "walk": {"en": "walk", "uk": "прогулянка"},
}


def tr(lang: Lang, key: str, **fields: object) -> str:
    text = STRINGS[key][lang]
    return text.format(**fields) if fields else text


def weekday(lang: Lang, day: date) -> str:
    return _WEEKDAYS[lang][day.weekday()]


def describe_weather(lang: Lang, code: int, english: str) -> str:
    return WMO_UK.get(code, "Невідомо") if lang == "uk" else english


def lang_from_code(language_code: str | None) -> Lang:
    return "uk" if (language_code or "").lower().startswith("uk") else DEFAULT_LANG


def resolve_lang(user_data: MutableMapping[str, Any] | None, language_code: str | None) -> Lang:
    chosen = (user_data or {}).get(KEY_LANG)
    if chosen in SUPPORTED:
        lang: Lang = chosen
        return lang
    return lang_from_code(language_code)
