"""Заміряти швидкість рендеру Stimreel на сервері GitHub (10 с, 720p, 30 fps)."""
import os, re, time, shutil
from playwright.sync_api import sync_playwright
os.makedirs("out", exist_ok=True)
HOOK = """(() => {const o=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){
 if(this.download&&this.href.startsWith('blob:')){fetch(this.href).then(r=>r.blob()).then(b=>{window.__b=b});return;}return o.apply(this,arguments)}})();"""
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True,
                          args=["--lang=en-US", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.add_init_script(HOOK)
    pg.goto("https://stimreel.com/generators/peg-drop?seed=12345", wait_until="domcontentloaded")
    btn = pg.get_by_role("button", name=re.compile(r"^(Render video|Download video)$"))
    btn.wait_for(timeout=60000)
    print("GPU:", pg.evaluate("(()=>{const g=document.createElement('canvas').getContext('webgl');const d=g&&g.getExtension('WEBGL_debug_renderer_info');return d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):'?'})()"), flush=True)
    for t in ("10 s", "720p", "30 fps"):
        pg.locator("label").filter(has_text=re.compile(rf"^\s*{t}\s*$")).first.click()
    t0 = time.time(); btn.click()
    last = ""
    while time.time() - t0 < 20 * 60:
        if pg.evaluate("!!window.__b"):
            print(f"DONE in {time.time()-t0:.0f}s, size {pg.evaluate('window.__b.size')}", flush=True); break
        txt = pg.inner_text("body"); m = re.search(r"(\d+\s?%[^\n]{0,60}|Rendering[^\n]{0,80}|frame[^\n]{0,60})", txt)
        cur = m.group(1) if m else ""
        if cur != last:
            print(f"{time.time()-t0:5.0f}s  {cur}", flush=True); last = cur
        time.sleep(5)
    else:
        print("NOT DONE in 20 min", flush=True)
    pg.screenshot(path="out/state.png")
    b.close()
