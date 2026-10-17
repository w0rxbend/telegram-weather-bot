<h1 align="center">telegram-weather-bot</h1>

<p align="center">
  Share your location once. Get a fresh, beautifully rendered weather infographic any time.
</p>

<p align="center">
  <img src="docs/preview-day.png" width="360" alt="Day card: showers in Kyiv" />
  &nbsp;&nbsp;
  <img src="docs/preview-night.png" width="360" alt="Night card: overcast in Kyiv" />
</p>

## What it does

1. `/start` – the bot asks for your location with Telegram's **📍 Share my location** button
   (or you can type a city name, handy on Telegram Desktop).
2. The location is saved per user and turned into a place name.
3. You get a PNG card with the current conditions, a 24-hour temperature curve with rain
   probability, and a 7-day outlook, themed by weather and time of day.
4. `/weather` – or the **🔄 Refresh** button under the picture – re-renders a fresh card.
   Refresh replaces the photo in place, so the chat stays tidy.

Everything is drawn with Pillow; no browser, no image assets, no API keys.

### Commands

| Command | What it does |
| --- | --- |
| `/start` | Welcome + location setup |
| `/weather` (`/now`, `/w`) | Fresh infographic for your saved location |
| `/setup` | Change the saved location |
| `/units` | Toggle °C / km/h ↔ °F / mph (also available as a button under each card) |
| `/help` | Command list |
| *any text* | One-off card for that city; your saved location stays unchanged |

## Run it

### Docker Compose (recommended)

```bash
cp .env.example .env            # put your bot token in TG_BOT_TOKEN
docker compose up -d
```

State (saved locations, unit preferences) lives in the `weather-bot-data` volume.
Set `WEATHER_BOT_IMAGE` to use a different image tag.

### Locally

Requires Python 3.11+ and [Poetry](https://python-poetry.org/) 2.x.

```bash
poetry install
cp .env.example .env            # add TG_BOT_TOKEN
poetry run weather-bot          # or: poetry run python -m weather_bot
```

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `TG_BOT_TOKEN` | – | Bot token from [@BotFather](https://t.me/BotFather). Required. |
| `DATA_DIR` | `./data` (`/data` in Docker) | Directory for the persistence file |
| `HTTP_TIMEOUT` | `15` | Seconds to wait for weather / geocoding requests |
| `USER_AGENT` | `telegram-weather-bot/1.0 (+repo url)` | Sent to Open-Meteo and Nominatim. Change it if you fork. |

## Development

```bash
poetry run pytest                 # unit tests (parsing, geocoding, rendering, handlers)
poetry run ruff check . && poetry run ruff format --check .
poetry run python scripts/preview.py                                  # live card for Kyiv -> preview.png
poetry run python scripts/preview.py 51.5 -0.12 London --units imperial
poetry run python scripts/preview.py --fixture tests/fixtures/forecast.json
```

`scripts/preview.py` is the fastest way to iterate on the design: it renders a card without
Telegram. `tests/make_fixture.py` regenerates the deterministic sample forecast used by tests.

### Project layout

```
src/weather_bot/
├── main.py          entry point, wires PTB Application + persistence
├── bot.py           Telegram handlers (setup, /weather, refresh / units buttons)
├── config.py        environment settings
├── weather.py       Open-Meteo client, Forecast model, WMO code mapping
├── geocode.py       Nominatim reverse geocoding, Open-Meteo city search
├── render/
│   ├── card.py      layout + composition of the infographic
│   ├── icons.py     procedurally drawn weather icons
│   ├── theme.py     palettes per condition/day-night, temperature colour ramp
│   └── fonts.py     bundled Inter font loader
└── assets/fonts/    Inter (SIL OFL 1.1)
```

### How a card is built

- Rendered at 2× (2160×3200) and downsampled with Lanczos, so text, curves and icons are
  antialiased.
- Background gradient and glow blobs come from the theme for the current condition and
  day/night flag.
- Hourly curve is a Catmull-Rom spline through the next 24 hourly temperatures, coloured by
  temperature; the bars beneath are precipitation probability.
- Daily columns show max/min with a vertical range bar positioned against the week's range.

## Data sources & credits

- Weather: [Open-Meteo](https://open-meteo.com/) (free for non-commercial use, no key).
- Reverse geocoding: [Nominatim / OpenStreetMap](https://nominatim.org/) – data © OpenStreetMap
  contributors, ODbL. The bot sends a single request per location setup and identifies itself
  with `USER_AGENT`, as their usage policy requires.
- City search: [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api).
- Typeface: [Inter](https://github.com/rsms/inter) by Rasmus Andersson, SIL Open Font License.

## License

MIT
