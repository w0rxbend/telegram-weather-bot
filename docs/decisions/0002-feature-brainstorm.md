# 0002 · Feature brainstorm and decisions (2026-10-21)

Context: the bot's core (cards, slots, schedule, telemetry) is stable. Question: what is worth
adding next, within "free data, no API keys, no new dependencies, little extra load"?

## Scoring
Value = how often a user would feel it. Cost = code + new failure modes + extra outbound calls.

| Idea | Value | Cost | Decision |
|---|---|---|---|
| Ukrainian + English chat text | high (audience) | medium: strings only, cards stay English | **Done** (`i18n.py`, `/lang`) |
| Rain alerts (opt-in push) | high: only feature that reaches the user unprompted | medium: reuses the forecast cache, needs cooldown | **Done** (`alerts.py`) |
| Air quality | medium | low: one free API | **Done** as `/air` (not on every card: +1 request per card) |
| Inline mode `@bot city` | medium: sharing = growth | low | **Done**; needs `/setinline` in @BotFather |
| `/compare` 2–3 cities | medium | low | **Done** |
| `/best run\|bike\|walk` | medium | low: pure function on hourly data | **Done** (`planner.py`) |
| Clothing / UV / umbrella line | medium | very low | **Done** (`advice.py`, previous commit) |
| `/forget`, 90-day log retention | required if public (GDPR) | low | **Done** (previous commit) |
| Sunset reminder preset | low–medium | medium: new schedule kind | Not now; listed in `TODO.md` |
| Threshold triggers (frost, wind) | medium | medium: generalises rain alerts | Next: extend `alerts.py` |
| Rain radar map | medium | high: new external source, tiles, licence | Rejected for now |
| Translating the PNG cards | low | high: layout changes per language | Rejected; chat text only |
| Render once per place for scheduled sends | scale only | medium | Not needed until user count grows (TODO P1) |
| Group-chat schedules | unclear | product decision | Deferred (F-23) |

## Design choices worth remembering
- **Language** is `/lang` choice, else Telegram `language_code`. The code is stored in `user_data`
  on every guarded update (`lang_code`) so background jobs (scheduler, alerts) can localise too.
- **Rain alerts** fire when any of the next 3 hours reaches 60% rain probability, at most once per
  6 hours, checked at most every 15 minutes per user, private chats only. The "sent" mark is
  persisted before sending (same rule as F-33), and a blocked user is unsubscribed.
- **/compare** costs up to 3 geocode + 3 forecast calls for one command, counted as one against the
  per-user rate limit. Forecasts come from the shared cache; geocoding is the uncached part.
- **Inline queries** are answered with `cache_time=300`, `is_personal=True` (units and language
  differ per user). Bad or empty queries get an empty answer without any network call.
- **Planner** works on hourly temperature, rain probability and daylight only. Hourly wind is not
  fetched today, so `/best` ignores wind.
