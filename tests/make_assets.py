"""Rebuild the icon PNGs and the README banner with LOCAL headless Edge.

  PYTHONPATH= uv run --no-project --with playwright python tests/make_assets.py

The banner card is rendered from the synthetic frozen fixture in test_weather.py,
never from live data.
"""
from pathlib import Path
import sys
import tempfile
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from test_weather import fixture, w, ROOT  # noqa: E402

THEME_VARS = ':root{--foreground:#ececee;--muted-foreground:#9a9ca3;--border:#34363c;--card:#1b1c20;color-scheme:dark}'

BANNER = """<!doctype html><meta charset="utf-8"><style>
body{margin:0;font-family:'Segoe UI',Inter,Helvetica,Arial,sans-serif;color:#ececee}
html,body{width:1200px;height:600px;overflow:hidden}
body{background:radial-gradient(900px 500px at 100% 0,#1b2230,transparent),#0f1013;display:flex;align-items:center;padding:0 80px;gap:56px;box-sizing:border-box}
.l{flex:1}.l img{width:120px;height:120px}
h1{font-size:64px;margin:46px 0 14px;font-weight:700;color:#f3f4f6;letter-spacing:-.5px}
p{font-size:26px;line-height:1.4;color:#9aa1ae;margin:0;max-width:520px}
.r{width:400px;flex:none;height:CLIPpx;overflow:hidden;
  -webkit-mask-image:linear-gradient(#000 calc(100% - 150px),transparent);mask-image:linear-gradient(#000 calc(100% - 150px),transparent)}
iframe{display:block;border:0;width:400px;height:FRAMEpx;background:transparent}</style>
<div class="l"><img src="ICON"><h1>Weather Cards</h1><p>Real forecasts your Hermes agent can show at a glance.</p></div>
<div class="r"><iframe src="CARD" scrolling="no"></iframe></div>"""

CLIP = 530  # visible card height; the rest fades out


def banner_card():
    raw = fixture()
    raw['city'] = 'Sample City'
    html = w.render(w.normalize(raw), unit='F', theme='dark')
    return html.replace('<style>', '<style>' + THEME_VARS, 1)


def main():
    assets, docs = ROOT / 'assets', ROOT / 'docs'
    docs.mkdir(exist_ok=True)
    icon = (assets / 'icon.svg').resolve().as_uri()
    with tempfile.TemporaryDirectory(prefix='wc-assets-') as temp, sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(device_scale_factor=1)
        ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(('file://', 'data:')) else r.abort())
        page = ctx.new_page()
        for size in (512, 256, 128, 64):
            page.set_viewport_size({'width': size, 'height': size})
            sheet = Path(temp) / 'icon.html'
            sheet.write_text(f'<style>body{{margin:0}}img{{display:block}}</style><img src="{icon}" width="{size}" height="{size}">', encoding='utf-8')
            page.goto(sheet.as_uri())
            page.wait_for_timeout(100)
            page.screenshot(path=str(assets / f'icon-{size}.png'), omit_background=True)

        card_file = Path(temp) / 'card.html'
        card_file.write_text(banner_card(), encoding='utf-8')
        page.set_viewport_size({'width': 400, 'height': 600})
        page.goto(card_file.as_uri())
        page.wait_for_selector('.day')
        frame_height = page.evaluate('Math.ceil(document.documentElement.scrollHeight)')

        banner = Path(temp) / 'banner.html'
        banner.write_text(BANNER.replace('ICON', icon).replace('CARD', card_file.as_uri())
                          .replace('CLIP', str(CLIP)).replace('FRAME', str(frame_height)), encoding='utf-8')
        page.set_viewport_size({'width': 1200, 'height': 600})
        page.goto(banner.as_uri())
        page.frame_locator('iframe').locator('.day').first.wait_for()
        page.wait_for_timeout(300)
        page.screenshot(path=str(docs / 'banner.png'))
        browser.close()
    print('Wrote assets/icon-{512,256,128,64}.png and docs/banner.png')


if __name__ == '__main__':
    main()
