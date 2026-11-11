"""1) що стається зі сторінкою після вибору картинок; 2) повна генерація без картинок."""
import os, re, shutil, sys, time
from playwright.sync_api import sync_playwright
import stimreel_gen
chrome = shutil.which("google-chrome")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=chrome, headless=True, args=["--lang=en-US"])
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("crash", lambda: print("PAGE CRASHED", flush=True))
    pg.on("console", lambda m: m.type in ("error",) and print("console:", m.text[:200], flush=True))
    pg.goto("https://stimreel.com/generators/peg-drop?seed=12345", wait_until="domcontentloaded")
    pg.get_by_role("button", name=re.compile(r"^(Render video|Download video)$")).wait_for(timeout=60000)
    pg.wait_for_timeout(3000)
    pg.locator("button[role=radio]").filter(has_text=re.compile("^Cats")).first.click()
    for t in (3, 15):
        pg.wait_for_timeout(t * 1000)
        try:
            print(f"+{t}s url={pg.url} body={pg.inner_text('body', timeout=5000)[:300]!r}", flush=True)
        except Exception as e:
            print(f"+{t}s ERR {e}", flush=True)
    b.close()
os.makedirs("out", exist_ok=True)
cfg = {"generate": {"browser_path": chrome or "", "length": 10, "images": "default", "generators": ["peg-drop", "marble-race"], "render_timeout_sec": 240}}
t = time.time()
made = stimreel_gen.generate(cfg, 2, "out", log=lambda m: print(m, flush=True))
print("RESULT:", made, f"{time.time()-t:.0f}s", flush=True)
sys.exit(0 if made else 1)
