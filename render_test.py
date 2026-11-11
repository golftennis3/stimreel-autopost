"""Діагностика: що бачить сервер GitHub на сторінці генератора Stimreel."""
import os, shutil, json
from playwright.sync_api import sync_playwright
os.makedirs("out", exist_ok=True)
chrome = shutil.which("google-chrome")
with sync_playwright() as p:
    for headless in (True, False):
        b = p.chromium.launch(executable_path=chrome, headless=headless,
                              args=["--lang=en-US", "--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        resp = pg.goto("https://stimreel.com/generators/peg-drop?seed=12345", wait_until="domcontentloaded")
        pg.wait_for_timeout(15000)
        tag = "headless" if headless else "xvfb"
        info = pg.evaluate("""async () => {
          const r = {url: location.href, title: document.title, webgl: !!document.createElement('canvas').getContext('webgl2'),
                     videoEncoder: typeof VideoEncoder !== 'undefined', ua: navigator.userAgent};
          if (r.videoEncoder) {
            for (const c of ['avc1.42001f','avc1.640028','vp09.00.10.08','av01.0.04M.08']) {
              try { r[c] = (await VideoEncoder.isConfigSupported({codec: c, width: 1080, height: 1920, bitrate: 6e6, framerate: 30})).supported; } catch (e) { r[c] = 'err ' + e; }
            }
          }
          r.buttons = [...document.querySelectorAll('button')].map(b => b.innerText.trim()).filter(Boolean).slice(0, 40);
          return r;
        }""")
        info["status"] = resp.status if resp else None
        print(tag, json.dumps(info, ensure_ascii=False, indent=1), flush=True)
        txt = pg.inner_text("body")
        i = txt.find("Export")
        print(tag, "EXPORT SECTION:", txt[i:i + 600] if i >= 0 else txt[:1500], flush=True)
        pg.screenshot(path=f"out/{tag}.png", full_page=False)
        b.close()
