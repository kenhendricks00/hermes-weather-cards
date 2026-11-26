#!/usr/bin/env python3
"""Fetch once from Open-Meteo, validate, and render a self-contained forecast card."""
import argparse
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

HOSTS = {'api.open-meteo.com', 'geocoding-api.open-meteo.com'}
CURRENT = ('temperature_2m', 'apparent_temperature', 'relative_humidity_2m', 'is_day', 'weather_code', 'wind_speed_10m')
DAILY = ('weather_code', 'temperature_2m_max', 'temperature_2m_min', 'precipitation_probability_max', 'sunrise', 'sunset')
HOURLY = ('temperature_2m', 'weather_code', 'is_day', 'precipitation_probability')
CODES = {0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 56: 'Freezing drizzle', 57: 'Freezing drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains', 80: 'Rain showers', 81: 'Rain showers', 82: 'Heavy showers', 85: 'Snow showers', 86: 'Snow showers', 95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with hail'}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def condition(code):
    return CODES.get(code, 'Unknown conditions')


def temperature(value, unit='C'):
    return None if value is None else value * 9 / 5 + 32 if unit == 'F' else value


def wind(value, unit='C'):
    return None if value is None else value / 1.609344 if unit == 'F' else value


def range_bar(low, high, scale_low, scale_high):
    if any(v is None for v in (low, high, scale_low, scale_high)):
        return None
    if low > high or scale_low > low or scale_high < high:
        raise ValueError('Invalid temperature range')
    span = scale_high - scale_low
    return (0, 100) if span == 0 else ((low - scale_low) / span * 100, (high - low) / span * 100)


def validate_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443) or p.fragment:
        raise ValueError('Only HTTPS Open-Meteo API URLs are allowed')
    if (p.hostname, p.path) not in {('api.open-meteo.com', '/v1/forecast'), ('geocoding-api.open-meteo.com', '/v1/search')}:
        raise ValueError('Unsupported API path')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('API redirect refused')


def fetch_json(url):
    validate_url(url)
    req = Request(url, headers={'User-Agent': 'hermes-weather-cards/1.0 (personal forecast card)', 'Accept': 'application/json'})
    with build_opener(NoRedirect).open(req, timeout=30) as response:
        data = response.read(4_000_001)
    if len(data) > 4_000_000:
        raise ValueError('API response too large')
    result = json.loads(data)
    if not isinstance(result, dict) or result.get('error'):
        raise ValueError('Open-Meteo error: ' + str(result.get('reason', 'invalid response')) if isinstance(result, dict) else 'Invalid API response')
    return result


def fetch(city, latitude=None, longitude=None, days=10):
    if not 1 <= days <= 14:
        raise ValueError('Forecast days must be 1 through 14')
    if (latitude is None) != (longitude is None):
        raise ValueError('Provide both latitude and longitude')
    location = None
    if latitude is None:
        geo = fetch_json('https://geocoding-api.open-meteo.com/v1/search?' + urlencode({'name': city, 'count': 5, 'language': 'en', 'format': 'json'}))
        places = geo.get('results', [])
        if not places:
            raise ValueError('Location not found. Supply explicit coordinates.')
        location = places[0]
        latitude, longitude = location['latitude'], location['longitude']
    if not number(latitude) or not number(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('Invalid coordinates')
    query = {'latitude': latitude, 'longitude': longitude, 'current': ','.join(CURRENT), 'daily': ','.join(DAILY), 'hourly': ','.join(HOURLY), 'timezone': 'auto', 'timeformat': 'unixtime', 'forecast_days': days, 'temperature_unit': 'celsius', 'wind_speed_unit': 'kmh'}
    data = fetch_json('https://api.open-meteo.com/v1/forecast?' + urlencode(query))
    return {'city': city, 'resolved_location': location, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'forecast': data}


def normalize(raw, city=None):
    if not isinstance(raw, dict):
        raise ValueError('Expected JSON object')
    data = raw.get('forecast', raw.get('results', raw))
    if not isinstance(data, dict) or data.get('error') or raw.get('error'):
        raise ValueError('Provider returned an error')
    tz = data.get('timezone')
    if not isinstance(tz, str) or not tz or len(tz) > 100:
        raise ValueError('Missing location timezone')
    current = data.get('current') or {}
    if not isinstance(current, dict) or not number(current.get('time')):
        raise ValueError('Source current.time must be Unix seconds. Request timeformat=unixtime; ISO wall times are ambiguous at DST.')
    if not 0 <= current['time'] <= 253402214400:
        raise ValueError('Source timestamp out of range')
    for section, fields in (('current', CURRENT), ('hourly', HOURLY), ('daily', DAILY)):
        values = data.get(section) or {}
        units = data.get(section + '_units') or {}
        if not isinstance(values, dict) or not isinstance(units, dict):
            raise ValueError('Invalid section: ' + section)
        for field in fields:
            if field.startswith('temperature') or field == 'apparent_temperature':
                expected = '°C'
            elif field == 'wind_speed_10m':
                expected = 'km/h'
            elif 'probability' in field or field == 'relative_humidity_2m':
                expected = '%'
            else:
                continue
            if field in values and units.get(field) != expected:
                raise ValueError('Expected canonical units for ' + field)
    def validate_value(field, value):
        if value is None:
            return
        if not number(value):
            raise ValueError('Non-numeric value: ' + field)
        if field == 'is_day' and value not in (0, 1):
            raise ValueError('is_day must be 0 or 1')
        if field == 'weather_code' and value != int(value):
            raise ValueError('Weather code must be an integer')
        if field == 'wind_speed_10m' and value < 0:
            raise ValueError('Wind speed cannot be negative')
    clean = {}
    for field in CURRENT:
        v = current.get(field)
        validate_value(field, v)
        clean[field] = v
    def rows(section, fields):
        group = data.get(section) or {}
        times = group.get('time', [])
        if not isinstance(times, list) or any(not number(t) for t in times):
            raise ValueError('Expected Unix timestamp array: ' + section)
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError('Timestamps must be strictly chronological')
        for field in fields:
            if field in group and (not isinstance(group[field], list) or len(group[field]) != len(times)):
                raise ValueError('Mismatched array length: ' + section + '.' + field)
        result = []
        for i, t in enumerate(times):
            row = {'time': t}
            for f in fields:
                v = group[f][i] if f in group else None
                validate_value(f, v)
                if 'probability' in f and v is not None and not 0 <= v <= 100:
                    raise ValueError('Precipitation outside 0 to 100')
                row[f] = v
            if section == 'daily' and row['temperature_2m_min'] is not None and row['temperature_2m_max'] is not None and row['temperature_2m_min'] > row['temperature_2m_max']:
                raise ValueError('Low exceeds high')
            result.append(row)
        return result
    daily, hourly = rows('daily', DAILY), rows('hourly', HOURLY)
    if clean['relative_humidity_2m'] is not None and not 0 <= clean['relative_humidity_2m'] <= 100:
        raise ValueError('Humidity outside 0 to 100')
    name = city if city is not None else raw.get('city', 'Forecast')
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError('City must be 1 to 200 characters')
    return {'city': name, 'timezone': tz, 'source_time': current['time'], 'retrieved_at': raw.get('retrieved_at'), 'current': clean, 'daily': daily[:14], 'hourly': hourly}


def hour_events(data, limit=24):
    start = data['source_time']
    future = [dict(r, kind='hour') for r in data['hourly'] if r['time'] > start][:limit]
    now = dict(data['current'], time=start, kind='now', precipitation_probability=None)
    # Probability is hourly, not an instantaneous observation. Use only the matching hour.
    matching = [r for r in data['hourly'] if r['time'] <= start < r['time'] + 3600]
    if matching:
        now['precipitation_probability'] = matching[-1]['precipitation_probability']
    end = future[-1]['time'] if future else start
    events = [now] + future
    for row in data['daily']:
        for kind in ('sunrise', 'sunset'):
            t = row[kind]
            if t is not None and start < t <= end:
                events.append({'time': t, 'kind': kind})
    return sorted(events, key=lambda r: (r['time'], r['kind']))


def render(data, unit='F', theme='auto'):
    if unit not in ('F', 'C') or theme not in ('auto', 'light', 'dark'):
        raise ValueError('Unsupported unit or theme')
    model = dict(data, events=hour_events(data), initial_unit=unit)
    payload = json.dumps(model, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = Path(__file__).with_name('card.html').read_text(encoding='utf-8')
    return template.replace('__TITLE__', html.escape(data['city'], quote=True)).replace('__THEME__', theme).replace('__DATA__', payload)


def error_html(error):
    return '<!doctype html><meta charset="utf-8"><title>Weather unavailable</title><body style="font:16px system-ui;padding:24px"><h2>Weather unavailable</h2><p role="alert">' + html.escape(str(error)) + '</p><p>No previous forecast was substituted. Retry explicitly when ready.</p></body>'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--city', help='Display city; geocoding selects first match, inspect resolved_location in raw JSON')
    p.add_argument('--latitude', type=float)
    p.add_argument('--longitude', type=float)
    p.add_argument('--days', type=int, default=10)
    p.add_argument('--input', type=Path, help='Offline saved Open-Meteo JSON with Unix times and C/kmh units')
    p.add_argument('--raw-output', type=Path)
    p.add_argument('--output', '-o', required=True, type=Path)
    p.add_argument('--unit', choices=('F', 'C'), default='F')
    p.add_argument('--theme', choices=('auto', 'light', 'dark'), default='auto')
    a = p.parse_args(argv)
    try:
        if not a.input and not a.city:
            raise ValueError('Provide --city or --input')
        raw = json.loads(a.input.read_text(encoding='utf-8')) if a.input else fetch(a.city, a.latitude, a.longitude, a.days)
        if a.raw_output:
            a.raw_output.parent.mkdir(parents=True, exist_ok=True)
            a.raw_output.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding='utf-8')
        page = render(normalize(raw, a.city), a.unit, a.theme)
        status = 0
    except Exception as exc:
        page, status = error_html(exc), 1
        print('Weather error: ' + str(exc), file=sys.stderr)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(page, encoding='utf-8')
    print(str(a.output.resolve()))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
