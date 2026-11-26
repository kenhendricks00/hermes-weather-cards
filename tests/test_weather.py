"""Offline, synthetic frozen fixtures. Never used by live fetch or demo."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/weather-cards/scripts/weather_card.py'
spec = importlib.util.spec_from_file_location('weather_card', SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def fixture():
    """Synthetic Nov 1-10 2025; spans US DST fallback. Unix seconds unambiguous."""
    stamp = 1761998400  # Frozen 2025-11-01 12:00 UTC
    daily_times = [1761969600, 1762056000] + [1762146000 + i * 86400 for i in range(8)]
    hourly = list(range(stamp - 3600, stamp + 48 * 3600, 3600))
    daily = {'time': daily_times, 'weather_code': [3, 61, 2, 0, 45, 71, 95, 63, 1, 80], 'temperature_2m_min': [5 + i for i in range(10)], 'temperature_2m_max': [12 + i for i in range(10)], 'precipitation_probability_max': [10] * 10, 'sunrise': [t + 7 * 3600 for t in daily_times], 'sunset': [t + 17 * 3600 for t in daily_times]}
    return {'city': 'Synthetic test city', 'forecast': {'timezone': 'America/New_York', 'current': {'time': stamp, 'temperature_2m': 10, 'apparent_temperature': 8, 'relative_humidity_2m': 50, 'weather_code': 2, 'wind_speed_10m': 16.09344, 'is_day': 1}, 'current_units': {'temperature_2m': '°C', 'apparent_temperature': '°C', 'wind_speed_10m': 'km/h', 'relative_humidity_2m': '%'}, 'daily': daily, 'daily_units': {'temperature_2m_min': '°C', 'temperature_2m_max': '°C', 'precipitation_probability_max': '%'}, 'hourly': {'time': hourly, 'temperature_2m': [10] * len(hourly), 'weather_code': [0] * len(hourly), 'is_day': [1] * len(hourly), 'precipitation_probability': [20] * len(hourly)}, 'hourly_units': {'temperature_2m': '°C', 'precipitation_probability': '%'}}}


class WeatherTests(unittest.TestCase):
    def test_normalize(self):
        d = w.normalize(fixture())
        self.assertEqual(len(d['daily']), 10)
        self.assertEqual(d['current']['temperature_2m'], 10)
        self.assertEqual(d['source_time'], fixture()['forecast']['current']['time'])

    def test_printing_press_envelope(self):
        raw = fixture()
        d = w.normalize({'meta': {}, 'results': raw['forecast']}, 'City')
        self.assertEqual(d['city'], 'City')

    def test_iso_rejected_not_guessed(self):
        f = fixture(); f['forecast']['current']['time'] = '2025-11-02T01:00'
        with self.assertRaisesRegex(ValueError, 'DST'):
            w.normalize(f)

    def test_unit_conversion(self):
        self.assertEqual(w.temperature(10, 'F'), 50)
        self.assertEqual(w.temperature(-40, 'F'), -40)
        self.assertAlmostEqual(w.wind(16.09344, 'F'), 10)
        self.assertEqual(w.wind(10, 'C'), 10)
        self.assertIsNone(w.temperature(None, 'F'))
        self.assertIsNone(w.wind(None, 'F'))

    def test_wrong_units(self):
        f = fixture(); f['forecast']['current_units']['temperature_2m'] = '°F'
        with self.assertRaises(ValueError): w.normalize(f)

    def test_codes(self):
        for code in (0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99):
            self.assertNotEqual(w.condition(code), 'Unknown conditions')
        self.assertEqual(w.condition(None), 'Unknown conditions')
        self.assertEqual(w.condition(999), 'Unknown conditions')

    def test_range_common_scale(self):
        self.assertEqual(w.range_bar(5, 15, 0, 20), (25, 50))
        self.assertEqual(w.range_bar(10, 10, 10, 10), (0, 100))
        self.assertIsNone(w.range_bar(None, 15, 0, 20))
        with self.assertRaises(ValueError): w.range_bar(15, 5, 0, 20)

    def test_missing_is_not_zero(self):
        f = fixture(); del f['forecast']['current']['wind_speed_10m']; del f['forecast']['hourly']['precipitation_probability']; f['forecast']['daily']['temperature_2m_min'][0] = None
        d = w.normalize(f)
        self.assertIsNone(d['current']['wind_speed_10m'])
        self.assertIsNone(d['hourly'][0]['precipitation_probability'])
        self.assertIsNone(d['daily'][0]['temperature_2m_min'])

    def test_missing_sections(self):
        f = fixture(); del f['forecast']['hourly']; del f['forecast']['daily']
        d = w.normalize(f)
        self.assertEqual(d['daily'], [])
        self.assertEqual(len(w.hour_events(d)), 1)

    def test_lengths(self):
        f = fixture(); f['forecast']['hourly']['weather_code'].pop()
        with self.assertRaisesRegex(ValueError, 'length'): w.normalize(f)

    def test_chronology(self):
        d = w.normalize(fixture()); ev = w.hour_events(d)
        self.assertEqual(ev, sorted(ev, key=lambda x: (x['time'], x['kind'])))
        self.assertEqual(ev[0]['kind'], 'now')
        self.assertIn('sunset', [r['kind'] for r in ev])
        self.assertIn('sunrise', [r['kind'] for r in ev])
        self.assertEqual(ev[0]['precipitation_probability'], 20)
        self.assertEqual(len([x for x in ev if x['kind'] == 'hour']), 24)

    def test_dst_hours_remain_distinct(self):
        d = w.normalize(fixture()); ev = w.hour_events(d, 48)
        # 05:00 and 06:00 UTC are distinct instances of 01:00 in New York.
        times = [r['time'] for r in ev if r['kind'] == 'hour']
        for t in (1762059600, 1762063200): self.assertIn(t, times)

    def test_escape_city_and_payload(self):
        d = w.normalize(fixture(), '</script><img src=x onerror=alert(1)> & "city"')
        page = w.render(d)
        self.assertNotIn('<img src=x', page)
        self.assertIn('\\u003c/script\\u003e', page)
        self.assertIn('&lt;/script&gt;', page)

    def test_urls(self):
        self.assertTrue(w.validate_url('https://api.open-meteo.com/v1/forecast?latitude=1'))
        for url in ('http://api.open-meteo.com/v1/forecast', 'file:///etc/passwd', 'https://api.open-meteo.com.evil.test/v1/forecast', 'https://api.open-meteo.com@evil.test/v1/forecast', 'https://api.open-meteo.com:8080/v1/forecast', 'https://api.open-meteo.com/other', 'https://api.open-meteo.com/v1/forecast#bad', 'javascript:alert(1)'):
            with self.subTest(url=url), self.assertRaises(ValueError): w.validate_url(url)

    def test_error_response(self):
        for data in ({'error': True, 'reason': 'bad'}, {'forecast': {'error': True}}, [], {}):
            with self.assertRaises(ValueError): w.normalize(data)
        self.assertIn('&lt;bad&gt;', w.error_html('<bad>'))

    def test_validation(self):
        for field, value in [('relative_humidity_2m', 200), ('temperature_2m', float('nan')), ('temperature_2m', '10'), ('is_day', 2), ('wind_speed_10m', -1), ('weather_code', 1.5)]:
            f = fixture(); f['forecast']['current'][field] = value
            with self.assertRaises(ValueError): w.normalize(f)
        f = fixture(); f['forecast']['hourly']['time'][1] = f['forecast']['hourly']['time'][0]
        with self.assertRaises(ValueError): w.normalize(f)
        f = fixture(); f['forecast']['daily']['precipitation_probability_max'][0] = 101
        with self.assertRaises(ValueError): w.normalize(f)
        f = fixture(); f['forecast']['daily']['temperature_2m_min'][0] = 100
        with self.assertRaises(ValueError): w.normalize(f)

    def test_cli_offline_and_visible_failure(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('HERMES_TEST_TMPDIR')) as tmp:
            p = Path(tmp); src = p / 'fixture.json'; out = p / 'card.html'
            src.write_text(json.dumps(fixture()), encoding='utf-8')
            with patch.object(w, 'fetch', side_effect=AssertionError('No network')):
                self.assertEqual(w.main(['--input', str(src), '-o', str(out)]), 0)
            self.assertIn('Synthetic test city', out.read_text(encoding='utf-8'))
            src.write_text('{"error":true}', encoding='utf-8')
            self.assertEqual(w.main(['--input', str(src), '-o', str(out)]), 1)
            self.assertIn('Weather unavailable', out.read_text(encoding='utf-8'))
            self.assertNotIn('Synthetic test city', out.read_text(encoding='utf-8'))

    def test_fetch_builds_explicit_request(self):
        with patch.object(w, 'fetch_json', return_value=fixture()['forecast']) as get:
            d = w.fetch('Display', 39.97, -75.13)
            url = get.call_args.args[0]
            for token in ('timeformat=unixtime', 'temperature_unit=celsius', 'forecast_days=10', 'wind_speed_unit=kmh', 'timezone=auto'):
                self.assertIn(token, url)
            self.assertIn('retrieved_at', d)
        for args in [('X', 91, 0), ('X', 0, 181), ('X', 1, None), ('X', 0, 0, 15)]:
            with self.assertRaises(ValueError): w.fetch(*args)

    def test_render_options(self):
        d = w.normalize(fixture())
        with self.assertRaises(ValueError): w.render(d, theme='dark"><img>')
        with self.assertRaises(ValueError): w.render(d, unit='K')

    def test_fetch_errors_are_not_forecasts(self):
        from unittest.mock import MagicMock
        from urllib.error import URLError
        for payload in (b'{"error":true,"reason":"bad request"}', b'[]', b'not JSON', b'x' * 4_000_001):
            response = MagicMock(); response.__enter__.return_value.read.return_value = payload
            opener = MagicMock(); opener.open.return_value = response
            with patch.object(w, 'build_opener', return_value=opener), self.assertRaises((ValueError, json.JSONDecodeError)):
                w.fetch_json('https://api.open-meteo.com/v1/forecast')
        with patch.object(w, 'build_opener', side_effect=URLError('offline')), self.assertRaises(URLError):
            w.fetch_json('https://api.open-meteo.com/v1/forecast')

    def test_redirect_refused(self):
        with self.assertRaisesRegex(ValueError, 'redirect'):
            w.NoRedirect().redirect_request(None, None, 302, 'found', {}, 'https://evil.test/')

    def test_no_private_api_or_browser_network(self):
        text = SCRIPT.with_name('card.html').read_text(encoding='utf-8')
        for token in ('fetch(', 'XMLHttpRequest', 'window.hermes', 'hermesDesktop', 'setInterval(', 'https://cdn'):
            self.assertNotIn(token, text)
        self.assertIn("connect-src 'none'", text)
        # The only message is the documented inline-preview size report, sent to the host frame.
        self.assertEqual(text.count('postMessage'), 1)
        self.assertIn("parent.postMessage({type:'hermes-inline-preview-size'", text)

    def test_card_blends_into_host_theme(self):
        text = SCRIPT.with_name('card.html').read_text(encoding='utf-8')
        self.assertIn('html,body{background:transparent}', text)
        self.assertNotIn('background:var(--background', text)

    def test_footer_uses_fetch_time(self):
        html = w.render(w.normalize(dict(fixture(), retrieved_at='2026-11-02T15:20:00+00:00')))
        self.assertIn('Updated ', html)
        self.assertIn('"retrieved_at": "2026-11-02T15:20:00+00:00"', html)


if __name__ == '__main__': unittest.main()
