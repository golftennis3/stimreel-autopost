"""Діагностика: від чого кнопка рендеру стає неактивною на сервері."""
import re, shutil
from playwright.sync_api import sync_playwright
JS_STATE = """() => { const b=[...document.querySelectorAll('button')].find(b=>/^(Render video|Download video)$/.test(b.innerText.trim()));
  return {disabled: b && b.disabled, near: b ? b.closest('section,div').parentElement.innerText.replace(/\\n+/g,' | ').slice(0,250) : 'no button'} }"""
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True, args=["--lang=en-US"])
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto("https://stimreel.com/generators/peg-drop?seed=12345", wait_until="domcontentloaded")
    pg.get_by_role("button", name=re.compile(r"^(Render video|Download video)$")).wait_for(timeout=60000)
    def st(label): print(label, pg.evaluate(JS_STATE), flush=True)
    st("loaded:")
    pg.wait_for_timeout(3000); st("after 3s:")
    try:
        pg.get_by_role("button", name=re.compile(r"^(Pause|Пауза)$")).first.click(timeout=3000); pg.wait_for_timeout(1500); st("after Pause:")
        pg.get_by_role("button", name=re.compile(r"^(Play|Resume|Відтворити)$")).first.click(timeout=3000); pg.wait_for_timeout(1500); st("after Play:")
    except Exception as e: print("pause err", e)
    pg.locator("button[role=radio]").filter(has_text=re.compile("^Cats")).first.click(); 
    for t in (0.5, 3, 10, 30): pg.wait_for_timeout(int(t*1000)); st(f"after Cats +{t}s:")
    n = pg.locator("input[type=number]").first; n.fill("13"); n.press("Tab")
    for t in (0.5, 5, 20): pg.wait_for_timeout(int(t*1000)); st(f"after number +{t}s:")
    b.close()
