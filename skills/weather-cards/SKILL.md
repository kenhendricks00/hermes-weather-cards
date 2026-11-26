---
name: weather-cards
description: "Use for weather requests. Fetch real forecasts as cards."
license: MIT
version: "1.0.0"
author: Kenneth Hendricks
---

# Weather Cards

Use this skill for current weather and forecast requests. Generate a real, static forecast snapshot and show it inline. This is a skill-generated HTML component, not a native Hermes-enforced tool. Fahrenheit/Celsius and Show more work locally without another model turn or network request.

## Procedure

1. Resolve the requested location. Ask only if ambiguous and no location context is available. Prefer explicit coordinates when known. Geocoding otherwise selects the first result; inspect the saved `resolved_location` before claiming it is the intended city. A city name is disclosed to Open-Meteo geocoding; coordinates are disclosed to its forecast API. Do not fetch a sensitive location without the user's intent.
2. Run the script in this skill's `scripts/` directory using Python 3.10+. Runtime is standard library only. Choose a writable output directory, preferably the active Hermes scratch directory. Example:

   ```bash
   python scripts/weather_card.py --city Philadelphia --latitude 39.97 --longitude -75.13 --days 10 --raw-output /chosen/scratch/forecast.json --output /chosen/scratch/forecast.html
   ```

   Replace paths for the actual skill directory and OS. Do not assume the working directory is the skill directory. Default unit is F; use `--unit C` if preferred. Theme defaults to system, `--theme light|dark` is available. Fetch once per explicit request. No polling, automatic refresh, stale cache fallback, API key, CLI install, upload or hosting.
3. Check exit status. On failure show the error card and explain the failure. Never reuse old weather silently. Inspect saved JSON and its provider timestamp; do not invent readings, fill missing fields with zero or call retrieval/render time the provider update time. The footer states current forecast valid time and that model update time is unavailable. Forecasts are not guarantees or severe-weather alerts.
4. Return a brief answer plus this on its own line using the actual absolute path:

   `::preview{file="/actual/absolute/path/forecast.html"}`

   If the surface cannot show previews, give the local file link and concise text from the same data. Do not claim native Desktop or phone integration was tested from a browser screenshot alone.

## Saved input

`--input /path/forecast.json` renders offline. It must be a real previously fetched response when answering a weather request. Clearly label age and never present a frozen fixture as live. The script accepts direct Open-Meteo objects, its saved `{city, retrieved_at, forecast}` envelope, or Printing Press `{meta, results}` envelopes containing the same fields. Numeric Unix timestamps and explicit C/kmh units are required. ISO wall times are rejected rather than guessed across DST. Missing fields display as a dash.

For the existing pp-weather-goat skill, no new installation is needed or authorized here. Its forecasts can be used only if they provide the required fields, canonical units and Unix timestamps. If they do not, use this script's direct Open-Meteo fetch for a complete card. Weather GOAT remains useful for NWS alerts and activity advice, which this card does not implement. Ignore any old claim that Open-Meteo is unlimited; follow current provider terms.

## Appearance and limits

Rounded theme-following card, current conditions, horizontally scrolling hourly forecast with chronological sunrise/sunset, daily bars on a common scale, tinted Today row, and 5-to-10/14-day expansion. Day rows are not selectable because they do not show day-specific hourly details. Original SVG icons, not Apple artwork; appearance differs from Apple Weather. Unit conversion happens in the browser from canonical C/kmh. UTC epochs are sorted without DST wall-time guessing; display uses the location's IANA timezone through browser Intl. The page makes no network calls. Attribution links navigate only when clicked.

## Disclosure

Explicit fetches contact `geocoding-api.open-meteo.com/v1/search` and `api.open-meteo.com/v1/forecast` over HTTPS. The services see your query or coordinates and network metadata. No telemetry, cookies, token stores, credentials, paid cloud browser or background process. Reads only the template and the chosen saved input; writes only chosen HTML and optional raw JSON. Free no-key API use is for non-commercial purposes and subject to rate limits and upstream terms, not an unlimited or commercial hosting promise. See [Terms and privacy](https://open-meteo.com/en/terms), [data licence and attribution](https://open-meteo.com/en/licence), and [commercial plans](https://open-meteo.com/en/pricing). MIT covers this code, not provider data. Do not remove Open-Meteo attribution.
