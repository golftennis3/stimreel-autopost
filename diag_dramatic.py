"""Діагностика кнопки «Find dramatic seeds»: що вона показує і скільки триває (на акаунті бота)."""
import os, re, shutil, time
from playwright.sync_api import sync_playwright
import stimreel_gen
g = stimreel_gen.settings({"generate": {}})
os.makedirs("out", exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True, args=["--lang=en-US"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
    ctx.add_cookies([{"name": "NEXT_LOCALE", "value": "en", "url": "https://stimreel.com"}])
    pg = ctx.new_page()
    print("login ok:", stimreel_gen.login_with_password(pg, g, os.environ["STIMREEL_EMAIL"], os.environ["STIMREEL_PASSWORD"], print), flush=True)
    for gen in ("last-thread", "peg-drop"):
        pg.goto(f"https://stimreel.com/generators/{gen}?seed=12345", wait_until="domcontentloaded")
        pg.get_by_role("button", name=re.compile(r"^(Render video|Download video)$")).wait_for(timeout=60000)
        stimreel_gen._pause_preview(pg)
        btn = pg.get_by_role("button", name=re.compile(r"Find dramatic seeds", re.I))
        print(gen, "dramatic buttons:", btn.count(), flush=True)
        if not btn.count():
            continue
        btn.first.click()
        t0 = time.time(); last = ""
        while time.time() - t0 < 600:
            sec = pg.evaluate("""() => { const h=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/Dramatic seeds/.test(e.textContent));
                if(!h) return 'no heading'; let s=h; for(let i=0;i<5;i++){ s=s.parentElement; if(s.innerText.length>200) break; }
                return s.innerText.replace(/\\n+/g,' | ').slice(0,700) }""")
            if sec != last:
                print(f"{gen} {time.time()-t0:5.0f}s: {sec}", flush=True); last = sec
            if re.search(r"(seed|Seed)[^|]*\\d{5,}", sec) and not re.search(r"(Replaying|Searching|\\d+\\s*/\\s*60|%)", sec):
                break
            time.sleep(5)
        info = pg.evaluate("""() => { const h=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/Dramatic seeds/.test(e.textContent));
            let s=h; for(let i=0;i<6;i++){ s=s.parentElement; } return [...s.querySelectorAll('button,a,[role=radio],[role=option]')].map(e=>(e.tagName+':'+(e.getAttribute('role')||'')+':'+e.innerText.trim().replace(/\\n/g,' ')).slice(0,80)) }""")
        print(gen, "CONTROLS:", info, flush=True)
        pg.screenshot(path=f"out/{gen}-dramatic.png", full_page=True)
    b.close()
