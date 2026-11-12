"""Діагностика: як сайт віддає обкладинку (Thumbnail → Download)."""
import os, re, shutil
from playwright.sync_api import sync_playwright
import stimreel_gen
g = stimreel_gen.settings({"generate": {}})
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True, args=["--lang=en-US"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    ctx.add_cookies([{"name": "NEXT_LOCALE", "value": "en", "url": "https://stimreel.com"}])
    pg = ctx.new_page()
    stimreel_gen.login_with_password(pg, g, os.environ["STIMREEL_EMAIL"], os.environ["STIMREEL_PASSWORD"], print)
    pg.goto("https://stimreel.com/generators/last-thread?seed=12345", wait_until="domcontentloaded")
    pg.get_by_role("button", name=re.compile(r"^(Render video|Download video)$")).wait_for(timeout=60000)
    stimreel_gen._pause_preview(pg)
    info = pg.evaluate("""() => { const h=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&e.textContent.trim()==='Thumbnail');
      if(!h) return 'no Thumbnail heading'; let s=h; for(let i=0;i<4;i++){ if(s.querySelector('a,button,img,canvas')) break; s=s.parentElement; }
      return {html: s.outerHTML.slice(0,1500)} }""")
    print("THUMB SECTION:", info, flush=True)
    link = pg.locator("a", has_text=re.compile(r"^\\s*Download\\s*$"))
    print("download links:", link.count(), [link.nth(i).get_attribute("href") and link.nth(i).get_attribute("href")[:80] for i in range(link.count())], [link.nth(i).get_attribute("download") for i in range(link.count())], flush=True)
    if link.count():
        try:
            with pg.expect_download(timeout=30000) as d:
                link.first.click()
            os.makedirs("out", exist_ok=True); path = "out/" + (d.value.suggested_filename or "thumb.bin"); d.value.save_as(path)
            print("DOWNLOADED", path, os.path.getsize(path), flush=True)
        except Exception as e:
            print("download err", e, flush=True)
    b.close()
