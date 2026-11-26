"""Optional local Edge-only UI verification. Runtime remains dependency-free.
Run: PYTHONPATH= uv run --no-project --with playwright python tests/browser_check.py
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from test_weather import fixture, w, ROOT


def check(page, file):
    requests, errors = [], []
    page.on('request', lambda r: requests.append(r.url) if r.url.startswith(('http:', 'https:')) else None)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(file.as_uri())
    page.wait_for_selector('.day')
    data = page.locator('#weather-data').text_content()
    d = json.loads(data)
    assert page.locator('.day').count() == min(5, len(d['daily']))
    for unit, button in [('C', '#celsius'), ('F', '#fahrenheit')]:
        page.click(button)
        assert page.locator(button).get_attribute('aria-pressed') == 'true'
        result = page.evaluate('''unit=>{
          const d=JSON.parse(document.querySelector('#weather-data').textContent);
          const v=x=>x==null?'—':Math.round(unit==='F'?x*9/5+32:x)+'°';
          const errors=[];
          if(document.querySelector('.temp').textContent!==v(d.current.temperature_2m))errors.push('current');
          const first=d.daily.find(x=>new Intl.DateTimeFormat('en-US',{timeZone:d.timezone}).format(x.time*1000)===new Intl.DateTimeFormat('en-US',{timeZone:d.timezone}).format(d.source_time*1000));
          const feels='Feels like '+v(d.current.apparent_temperature)+' · H:'+v(first?.temperature_2m_max)+' L:'+v(first?.temperature_2m_min);
          if(document.querySelector('#feels').textContent!==feels)errors.push('feels and H/L');
          const speed=d.current.wind_speed_10m;
          const expected='Wind '+(speed==null?'—':Math.round(unit==='F'?speed/1.609344:speed))+' '+(unit==='F'?'mph':'km/h');
          if(!document.querySelector('#wind').textContent.startsWith(expected))errors.push('wind');
          document.querySelectorAll('.day').forEach((row,i)=>{
            if(row.querySelector('.low').textContent!==v(d.daily[i].temperature_2m_min))errors.push('low '+i);
            if(row.querySelector('.high').textContent!==v(d.daily[i].temperature_2m_max))errors.push('high '+i);
          });
          document.querySelectorAll('.hour').forEach((row,i)=>{
            if(['hour','now'].includes(d.events[i].kind)&&row.querySelector('.hour-temp').textContent!==v(d.events[i].temperature_2m))errors.push('hour '+i);
          });return errors;
        }''', unit)
        assert not result, result
    bar_before = page.locator('.range').evaluate_all('(xs)=>xs.map(x=>[x.style.left,x.style.width])')
    values = [r[k] for r in d['daily'] for k in ('temperature_2m_min', 'temperature_2m_max') if r[k] is not None]
    low, high = min(values), max(values)
    for row, actual in zip(d['daily'][:5], bar_before):
        expected = w.range_bar(row['temperature_2m_min'], row['temperature_2m_max'], low, high)
        assert abs(float(actual[0].strip('%')) - expected[0]) < .001
        assert abs(float(actual[1].strip('%')) - expected[1]) < .001
    page.click('#celsius')
    assert page.locator('.range').evaluate_all('(xs)=>xs.map(x=>[x.style.left,x.style.width])') == bar_before
    if len(d['daily']) > 5:
        page.click('#more'); assert page.locator('.day').count() == len(d['daily'])
        assert page.locator('#more').get_attribute('aria-expanded') == 'true'
        page.click('#more'); assert page.locator('.day').count() == 5
    page.locator('#hours').evaluate('(x)=>x.scrollLeft=250')
    assert page.locator('#hours').evaluate('(x)=>x.scrollLeft') > 0
    assert not page.locator('.day button').count()  # No fake day-specific detail interaction.
    times = page.locator('.hour').evaluate_all('(xs)=>xs.map(x=>Number(x.dataset.time))')
    assert times == sorted(times)
    assert len(times) == len(d['events'])
    assert page.locator('.today').count() == 1
    for mode in ('light', 'dark'):
        page.emulate_media(color_scheme=mode)
        for width in (360, 390, 640, 960):
            page.set_viewport_size({'width': width, 'height': 1050})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (mode, width, 'overflow')
            assert page.locator('.card').evaluate('(x)=>x.getBoundingClientRect().width') <= 640
            colors = page.locator('.card').evaluate('(x)=>[getComputedStyle(x).color,getComputedStyle(x).backgroundColor]')
            assert colors[0] != colors[1], colors
    assert not requests, requests
    assert not errors, errors
    return d


def main():
    p = argparse.ArgumentParser(); p.add_argument('--live', type=Path); p.add_argument('--screenshots', action='store_true'); a = p.parse_args()
    with tempfile.TemporaryDirectory(dir=os.environ.get('HERMES_TEST_TMPDIR')) as tmp, sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 1050}, device_scale_factor=1)
        f = Path(tmp) / 'frozen.html'; f.write_text(w.render(w.normalize(fixture())), encoding='utf-8')
        d = check(page, f)
        # Icons vary with day/night without outside artwork; DST duplicates retained.
        assert page.evaluate('icon(0,true)!==icon(0,false)')
        assert page.evaluate("fmt(1762059600,{hour:'numeric'})===fmt(1762063200,{hour:'numeric'})")
        fourteen = fixture()
        for key, values in fourteen['forecast']['daily'].items():
            tail = values[-1]
            values.extend([tail + 86400 * i if key in ('time', 'sunrise', 'sunset') else tail for i in range(1, 5)])
        f.write_text(w.render(w.normalize(fourteen)), encoding='utf-8')
        check(page, f)
        print('PASS: 14-day Show more / Show less')
        hostile = fixture(); hostile['city'] = '</script><img src=x onerror=alert(1)>'
        hostile['forecast']['current']['temperature_2m'] = None
        hostile['forecast']['current']['wind_speed_10m'] = None
        hostile['forecast']['daily']['temperature_2m_min'][0] = None
        f.write_text(w.render(w.normalize(hostile)), encoding='utf-8'); page.goto(f.as_uri())
        assert page.locator('.temp').text_content() == '—'
        assert page.locator('#wind').text_content().startswith('Wind —')
        assert page.locator('.day .low').first.text_content() == '—'
        assert page.locator('img').count() == 0
        assert page.locator('h1').text_content() == hostile['city']
        print('PASS: synthetic controls, all unit fields, common-scale bars, missing values, escaping, DST, theme and 360/390/640/960px overflow; no browser network')
        if a.live:
            live = check(page, a.live.resolve())
            if a.screenshots:
                docs = ROOT / 'docs'; docs.mkdir(exist_ok=True)
                for mode, width, name in [('dark', 800, 'desktop-dark.png'), ('dark', 390, 'phone-dark.png'), ('light', 390, 'phone-light.png')]:
                    page.emulate_media(color_scheme=mode); page.set_viewport_size({'width': width, 'height': 1100}); page.click('#fahrenheit'); page.locator('#hours').evaluate('(x)=>x.scrollLeft=0')
                    page.screenshot(path=str(docs / name), full_page=True)
            print('PASS: live '+live['city']+'; source_time='+str(live['source_time'])+'; daily='+str(len(live['daily']))+'; hours='+str(len(live['hourly'])))
        browser.close()


if __name__ == '__main__': main()
