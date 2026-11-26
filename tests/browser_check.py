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
        more = page.locator('#more')
        assert more.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgba(0, 0, 0, 0)'
        more.hover(); page.wait_for_timeout(250)
        assert more.evaluate('e=>getComputedStyle(e).backgroundColor') != 'rgba(0, 0, 0, 0)', 'Show more needs a hover pill'
        assert more.evaluate('e=>getComputedStyle(e).borderRadius') in ('999px', '9999px')
        page.mouse.move(0, 0)
        page.click('#more'); assert page.locator('.day').count() == len(d['daily'])
        assert page.locator('#more').get_attribute('aria-expanded') == 'true'
        page.click('#more'); assert page.locator('.day').count() == 5
    page.locator('#hours').evaluate('(x)=>x.scrollLeft=250')
    assert page.locator('#hours').evaluate('(x)=>x.scrollLeft') > 0
    times = page.locator('.hour').evaluate_all('(xs)=>xs.map(x=>Number(x.dataset.time))')
    assert times == sorted(times)
    assert len(times) == len(d['events'])
    assert page.locator('.today').count() == 1
    check_days(page, d)
    gap = page.evaluate("(()=>{const r=[...document.querySelectorAll('#days .day')].map(e=>e.getBoundingClientRect());return r.length>1?r[1].top-r[0].bottom:9})()")
    assert gap >= 3, ('day rows touch', gap)
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == 'rgba(0, 0, 0, 0)', 'card page must not paint its own background'
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


def check_days(page, d):
    """Selecting a day shows that day's numbers and hours; Today restores current conditions."""
    rows = page.locator('#days .day')
    if rows.count() < 2:
        return
    page.click('#fahrenheit')
    now_temp = page.locator('#hero .temp').text_content()
    assert rows.first.get_attribute('aria-pressed') == 'true'
    rows.nth(1).click()
    assert rows.nth(1).get_attribute('aria-pressed') == 'true' and rows.first.get_attribute('aria-pressed') == 'false'
    assert page.locator('#days .day.selected').count() == 1
    assert page.locator('#hero .temp').text_content() == rows.nth(1).locator('.high').text_content()
    label = page.locator('#hours-label').text_content()
    assert label != 'Hourly forecast', label
    first_hour = page.locator('#hours .hour-time').first.text_content()
    assert first_hour != 'Now', first_hour
    times = page.locator('.hour').evaluate_all('(xs)=>xs.map(x=>Number(x.dataset.time))')
    assert times == sorted(times)
    page.click('#celsius'); assert rows.nth(1).get_attribute('aria-pressed') == 'true'
    page.click('#fahrenheit')
    rows.first.click()
    assert page.locator('#hours-label').text_content() == 'Hourly forecast'
    assert page.locator('#hours .hour-time').first.text_content() == 'Now'
    assert page.locator('#hero .temp').text_content() == now_temp


def check_hour_controls(browser, file):
    """Arrows appear only on hover with a mouse; touch screens swipe with no arrows or scrollbar."""
    page = browser.new_page(viewport={'width': 560, 'height': 900})
    page.goto(file.as_uri())
    hours, nxt = page.locator('#hours'), page.locator('#hours-next')
    assert hours.evaluate('e=>e.offsetHeight-e.clientHeight') == 0, 'visible scrollbar'
    assert nxt.evaluate('e=>getComputedStyle(e).opacity') == '0'
    page.locator('.hours-wrap').hover(); page.wait_for_timeout(250)
    assert nxt.evaluate('e=>getComputedStyle(e).opacity') == '1'
    before = hours.evaluate('e=>e.scrollLeft'); nxt.click(); page.wait_for_timeout(700)
    assert hours.evaluate('e=>e.scrollLeft') > before
    assert page.locator('#hours-prev').is_visible()
    track = page.locator('.units').evaluate('e=>getComputedStyle(e).backgroundColor')
    assert track != 'rgba(0, 0, 0, 0)', 'desktop unit control should be a switch track'
    page.close()
    ctx = browser.new_context(viewport={'width': 390, 'height': 900}, has_touch=True, is_mobile=True)
    page = ctx.new_page(); page.goto(file.as_uri())
    assert page.locator('.units').evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgba(0, 0, 0, 0)', 'touch keeps the separate buttons'
    assert page.evaluate("matchMedia('(hover:none)').matches")
    assert page.locator('#hours-next').evaluate('e=>getComputedStyle(e).display') == 'none'
    box = page.locator('#hours').bounding_box(); cdp = ctx.new_cdp_session(page)
    x, y = box['x'] + box['width'] * .8, box['y'] + box['height'] / 2
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
    for i in range(1, 16):
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': x - i * 17, 'y': y}]}); page.wait_for_timeout(16)
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []}); page.wait_for_timeout(500)
    assert page.locator('#hours').evaluate('e=>e.scrollLeft') > 50, 'swipe did not move the hourly forecast'
    ctx.close()


HOST = """<!doctype html><html><body style="margin:0;background:#141414">
<span id="w" style="display:block;position:relative;height:280px;width:560px"><iframe id="f" sandbox="allow-scripts" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></span>
<script>const T="tok123";document.getElementById('f').srcdoc=SRC;
addEventListener('message',e=>{const d=e.data;if(!d||d.type!=='hermes-inline-preview-size'||d.token!==T)return;document.getElementById('w').style.height=Math.min(1200,Math.max(120,Math.round(d.height)))+'px'});</script></body></html>"""
INJECT = ('<script>(function(){var t="tok123";var lastH=0;function post(){var d=document.documentElement;var h=d.scrollHeight;'
          'if(Math.abs(h-lastH)>1){lastH=h;parent.postMessage({type:"hermes-inline-preview-size",token:t,height:h},"*")}}'
          'addEventListener("load",post);post()})()</' + 'script>')


def check_host_sizing(browser, file, tmp):
    """Mimic Hermes' inline preview frame (starts at 280px, never shrinks itself) and confirm the card resizes it."""
    card = file.read_text(encoding='utf-8') + INJECT
    host = Path(tmp) / 'host.html'
    host.write_text(HOST.replace('SRC', json.dumps(card).replace('</', '<\\/')), encoding='utf-8')
    page = browser.new_page(viewport={'width': 600, 'height': 1300}); page.goto(host.as_uri()); page.wait_for_timeout(1800)
    frame = page.frame_locator('#f')
    tall = lambda: page.locator('#w').evaluate('e=>e.getBoundingClientRect().height')
    card_h = lambda: frame.locator('.card').evaluate('e=>Math.ceil(e.getBoundingClientRect().bottom)')
    h1 = tall(); assert abs(h1 - min(1200, card_h() + 2)) <= 3, (h1, card_h())
    if frame.locator('#more').is_visible():
        frame.locator('#more').click(); page.wait_for_timeout(800); h2 = tall()
        assert h2 > h1 + 50, ('Show more did not grow the frame', h1, h2)
        frame.locator('#more').click(); page.wait_for_timeout(800)
        assert abs(tall() - h1) <= 3, ('frame did not shrink back', h1, tall())
    page.close()
    return h1


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
        f.write_text(w.render(w.normalize(fourteen)), encoding='utf-8')
        check_hour_controls(browser, f)
        h = check_host_sizing(browser, f, tmp)
        print('PASS: hover-only arrows, touch swipe, inline frame sizing (' + str(int(h)) + 'px, grows and shrinks with Show more)')
        print('PASS: synthetic controls, day selection, row gaps, transparent background, all unit fields, common-scale bars, missing values, escaping, DST, theme and 360/390/640/960px overflow; no browser network')
        if a.live:
            live = check(page, a.live.resolve())
            if a.screenshots:
                docs = ROOT / 'docs'; docs.mkdir(exist_ok=True)
                for mode, width, name in [('dark', 800, 'desktop-dark.png'), ('dark', 390, 'phone-dark.png'), ('light', 390, 'phone-light.png')]:
                    page.emulate_media(color_scheme=mode); page.set_viewport_size({'width': width, 'height': 1100}); page.click('#fahrenheit'); page.locator('#hours').evaluate('(x)=>x.scrollLeft=0')
                    box = page.locator('.card').bounding_box(); page.screenshot(path=str(docs / name), clip={'x': 0, 'y': 0, 'width': width, 'height': box['y'] + box['height'] + 2})
            print('PASS: live '+live['city']+'; source_time='+str(live['source_time'])+'; daily='+str(len(live['daily']))+'; hours='+str(len(live['hourly'])))
        browser.close()


if __name__ == '__main__': main()
