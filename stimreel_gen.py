"""
stimreel_gen.py — генерує відео на stimreel.com (сайт власника) і кладе MP4 у чергу.

Як працює:
  * login.bat відкриває ЗВИЧАЙНИЙ Chrome з окремим профілем скрипта (browser-profile),
    власник один раз входить у свій акаунт Stimreel.
  * Для генерації скрипт запускає той самий звичайний Chrome з тим самим профілем
    (тож вхід і рендер без водяного знака зберігаються) і підключається до нього
    через DevTools-порт. Готове відео забирає прямо зі сторінки, без вікна «Зберегти».

Потрібен пакет:  pip install playwright   (браузер не завантажується — береться твій Chrome)
"""
import base64
import json
import os
import random
import re
import socket
import subprocess
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "browser-profile")
HISTORY_PATH = os.path.join(HERE, "history.json")
FALLBACK_GENERATORS = ["peg-drop", "marble-bounce", "block-rush", "merge-drop",
                       "stair-bounce", "last-square", "last-thread", "marble-race"]
RECENT_KEEP = 1000  # скільки останніх генерацій пам'ятати

DEFAULTS = {
    "lang": "en",               # мова сайту: "en" (англійська) або "uk"
    "generators": "auto",       # "auto" — брати всі генератори з сайту (нові додаються самі) або список
    "length": 20,               # секунд: 10 / 20 / 30 / 60
    "resolution": "1080p",      # 720p / 1080p / 4K
    "fps": 30,                  # 30 / 60
    "images": "random",         # набір картинок: "random", "default" або список, напр. ["Cats", "Animals"]
    "randomize": True,          # перемішувати параметри генератора (числа, палітра, розкладка, звук)
    "random_strength": 0.7,     # 0..1 — яку частину діапазону кожного параметра використовувати
    "keep": [],                 # назви параметрів, які не чіпати, напр. ["Gravity", "Palette"]
    "description": "Instagram Reels",  # з якої вкладки «Post description» брати опис ("" — не брати)
    "headless": True,           # рендерити без видимого вікна
    "browser_path": "",         # шлях до chrome.exe, якщо не знаходиться сам
    "render_timeout_sec": 600,
    "min_queue": 2,             # перед публікацією в черзі має бути хоча б стільки відео
}

# Перехоплюємо збереження відео: сайт створює blob і «клікає» посилання download.
HOOK = r"""
(() => {
  const orig = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.download && this.href && this.href.startsWith('blob:')) {
      window.__srName = this.download;
      fetch(this.href).then(r => r.blob()).then(b => { window.__srBlob = b; });
      return;
    }
    return orig.apply(this, arguments);
  };
})();
"""

READ_CHUNK = r"""
async ([s, e]) => {
  const u = new Uint8Array(await window.__srBlob.slice(s, e).arrayBuffer());
  let bin = '';
  for (let i = 0; i < u.length; i += 0x8000) bin += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(bin);
}
"""


LANG = {
    "en": {"render": "Render video", "decline": re.compile(r"^(Decline|Reject|Reject all)$", re.I),
           "sec": "{} s", "fps": "{} fps", "default": "default"},
    "uk": {"render": "Відрендерити відео", "decline": re.compile(r"^Відхилити$"),
           "sec": "{} с", "fps": "{} кадр/с", "default": "за замовчуванням"},
}


def _num(v):
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else v


def settings(cfg):
    g = dict(DEFAULTS)
    g.update(cfg.get("generate") or {})
    g["lang"] = g.get("lang") if g.get("lang") in LANG else "en"
    L = LANG[g["lang"]]
    # англійська версія — без префікса (stimreel.com/generators/…), українська — /uk
    g["site"] = g.get("site") or ("https://stimreel.com" if g["lang"] == "en" else "https://stimreel.com/uk")
    g["L"] = L
    g["_stats"] = cfg.get("stats") or {}
    g["length_label"] = L["sec"].format(_num(g["length"]))
    g["fps_label"] = L["fps"].format(_num(g["fps"]))
    return g


def _find_browser(g=None):
    if g and g.get("browser_path") and os.path.exists(g["browser_path"]):
        return g["browser_path"]
    import shutil as _sh
    cands = []
    for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")):
        if base:
            cands += [os.path.join(base, r"Google\Chrome\Application\chrome.exe"),
                      os.path.join(base, r"Microsoft\Edge\Application\msedge.exe")]
    for c in cands:
        if os.path.exists(c):
            return c
    return _sh.which("chrome") or _sh.which("google-chrome") or _sh.which("msedge")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_chrome(exe, headless):
    port = _free_port()
    args = [exe, f"--user-data-dir={PROFILE_DIR}", f"--remote-debugging-port={port}",
            "--no-first-run", "--no-default-browser-check", "--window-size=1280,900",
            "--autoplay-policy=no-user-gesture-required", "--lang=en-US",
            "--disable-component-update", "--disable-background-networking",
            "--disable-features=OptimizationHints,MediaRouter", "--log-level=3"]
    if headless:
        args.append("--headless=new")
    # службові повідомлення Chrome (оновлення тощо) у консоль не виводимо
    proc = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            return proc, port
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Chrome не запустився. Закрий вікна Chrome, відкриті через login.bat, і спробуй ще раз.")


def _exact(page, text):
    return page.locator("label").filter(has_text=re.compile("^\\s*" + re.escape(text) + "\\s*$"))


def _logged_in(page):
    """На сторінці немає кнопки/посилання «Увійти» — значить, ми в акаунті."""
    try:
        return page.get_by_role("link", name="Увійти").count() == 0 and \
               page.get_by_role("button", name="Увійти").count() == 0
    except Exception:  # noqa: BLE001
        return False


def _pick_images(page, g, avoid=None, hist=None):
    """Обрати набір картинок (кнопки-радіо «За замовчуванням», «Cats», …). Повертає назву або None."""
    want = g.get("images", "random")
    if want in (None, "", "default"):
        return None
    try:
        opts = page.locator("button[role=radio]")
        n = opts.count()
        names = [re.split(r"\s*(?:\n|зображень|\d+\s+pictures?|images?:)", opts.nth(i).inner_text().strip())[0].strip()
                 for i in range(n)]
        if not names:
            return None  # у цього генератора немає наборів картинок
        if want == "random":
            pool = list(range(n))
        else:
            dflt = g["L"]["default"]
            alias = {"default": dflt, "дефолт": dflt, "за замовчуванням": dflt}
            wanted = {alias.get(w.strip().lower(), w.strip().lower()) for w in want}
            pool = [i for i, nm in enumerate(names) if nm.lower() in wanted]
            if not pool:
                return None
        if avoid and len(pool) > 1:  # не ті набори, що були щойно
            pool = [i for i in pool if names[i] not in avoid] or pool
        perf = {}
        if hist is not None:
            try:
                import stats
                perf = stats.weights({"stats": g.get("_stats", {})}, hist, "images", [names[i] for i in pool])
            except Exception:  # noqa: BLE001
                perf = {}
        i = random.choices(pool, weights=[perf.get(names[i], 1.0) for i in pool])[0]
        opts.nth(i).click(timeout=5000)
        page.wait_for_timeout(1500)  # дати картинкам завантажитися
        return names[i]
    except Exception:  # noqa: BLE001
        return None


def _read_description(page, g):
    """Після рендеру сайт показує «Post description» з вкладками платформ — беремо потрібну."""
    tab_name = g.get("description")
    if not tab_name:
        return ""
    try:
        # вкладки платформ на сайті — це перемикачі з підписами (label), а не кнопки
        tab = _exact(page, tab_name)
        if tab.count() == 0:
            tab = page.get_by_role("tab", name=tab_name).or_(page.get_by_role("button", name=tab_name))
        tab.first.wait_for(timeout=15000)
        tab.first.click(timeout=5000)
        page.wait_for_timeout(800)
        boxes = page.locator("textarea")
        for i in range(boxes.count() - 1, -1, -1):
            text = boxes.nth(i).input_value().strip()
            if text:
                return text
    except Exception:  # noqa: BLE001
        pass
    return ""


def _fmt(v, step):
    if step and float(step).is_integer():
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _randomize(page, g):
    """Випадкові значення для всіх параметрів генератора у «All settings». Повертає опис змін."""
    if not g.get("randomize", True):
        return []
    changed = []
    keep = [k.lower() for k in g.get("keep", [])]
    try:
        page.get_by_role("tab", name=re.compile(r"^\s*(All settings|Усі налаштування)")).first.click(timeout=3000)
    except Exception:  # noqa: BLE001
        pass
    try:
        page.get_by_role("button", name=re.compile(r"(Show advanced settings|Показати)", re.I)).first.click(timeout=2000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(400)
    band = max(0.0, min(1.0, float(g.get("random_strength", 0.7))))

    nums = page.locator("input[type=number]")
    for i in range(nums.count()):
        n = nums.nth(i)
        try:
            if not n.is_visible():
                continue
            label = (n.get_attribute("aria-label") or "").strip()
            if re.search(r"volume|гучн", label, re.I) or label.lower() in keep:
                continue
            lo, hi = float(n.get_attribute("min")), float(n.get_attribute("max"))
            step_attr = n.get_attribute("step")
            step = float(step_attr) if step_attr and step_attr != "any" else None
            mid, half = (lo + hi) / 2, (hi - lo) / 2 * band
            v = random.uniform(mid - half, mid + half)
            if step:
                v = lo + round((v - lo) / step) * step
            v = max(lo, min(hi, v))
            txt = _fmt(v, step)
            n.fill(txt)
            n.press("Tab")
            changed.append(f"{label} {txt}")
        except Exception:  # noqa: BLE001
            continue

    combos = page.locator("button[role=combobox]")
    for i in range(combos.count()):
        c = combos.nth(i)
        try:
            if not c.is_visible():
                continue
            label = c.evaluate("e => (e.id && document.querySelector(`label[for=\"${e.id}\"]`)?.innerText) || e.getAttribute('aria-label') || ''").strip()
            if label.lower() in keep:
                continue
            c.click(timeout=3000)
            page.wait_for_timeout(300)
            opts = page.get_by_role("option")
            k = opts.count()
            if k:
                o = opts.nth(random.randrange(k))
                name = o.inner_text().strip()
                o.click(timeout=3000)
                changed.append(f"{label} {name}".strip())
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:  # noqa: BLE001
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
    return changed


# ---------- журнал генерацій і пошук нових ігор ----------

def _load_hist():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            h = json.load(f)
    except Exception:  # noqa: BLE001
        h = {}
    h.setdefault("known", [])     # генератори, знайдені на сайті
    h.setdefault("checked", "")   # коли востаннє перевіряли сайт
    h.setdefault("recent", [])    # останні генерації: gen, seed, images, file, time
    return h


def _save_hist(h):
    h["recent"] = h["recent"][-RECENT_KEEP:]
    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=1)
    os.replace(tmp, HISTORY_PATH)


def _generators(page, g, hist, log, force=False):
    """Список генераторів. У режимі "auto" раз на день перевіряє сторінку Generators на сайті."""
    if isinstance(g["generators"], list) and g["generators"] and not force:
        return g["generators"]
    today = datetime.now().strftime("%Y-%m-%d")
    if force or hist["checked"] != today or not hist["known"]:
        try:
            page.goto(f"{g['site']}/generators", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            found = page.evaluate("""() => [...new Set([...document.querySelectorAll('a[href*="/generators/"]')]
                .map(a => new URL(a.href).pathname.split('/generators/')[1] || '')
                .map(s => s.split(/[/?#]/)[0]).filter(Boolean))]""")
            if found:
                new = [x for x in found if x not in hist["known"]]
                gone = [x for x in hist["known"] if x not in found]
                if hist["known"] and new:
                    log("Нові ігри на сайті: " + ", ".join(new) + " — додано до генерації.")
                if gone:
                    log("Зникли з сайту: " + ", ".join(gone) + " — більше не генеруються.")
                hist["known"] = found
                hist["checked"] = today
                _save_hist(hist)
        except Exception as e:  # noqa: BLE001
            log(f"Не вдалося перевірити список ігор на сайті: {e}")
    return hist["known"] or FALLBACK_GENERATORS


def _choose_generator(gens, hist, g=None):
    """Не той, що був нещодавно; частіше — ті, що давно не випадали."""
    recent = [r.get("gen") for r in hist["recent"]]
    avoid_n = min(len(gens) - 1, 3)
    last = []
    for r in reversed(recent):
        if len(last) >= avoid_n:
            break
        if r not in last:
            last.append(r)
    pool = [x for x in gens if x not in last] or list(gens)

    def age(name):  # скільки генерацій тому був цей генератор
        for k, r in enumerate(reversed(recent)):
            if r == name:
                return k
        return 100

    try:  # статистика: ігри, що набирають більше, випадають частіше
        import stats
        perf = stats.weights({"stats": g.get("_stats", {})}, hist, "gen", pool)
    except Exception:  # noqa: BLE001
        perf = {}
    return random.choices(pool, weights=[(min(age(x), 100) + 1) * perf.get(x, 1.0) for x in pool])[0]


def _new_seed(gen, hist):
    used = {r.get("seed") for r in hist["recent"] if r.get("gen") == gen}
    while True:
        seed = random.randint(1, 4294967295)
        if seed not in used:
            return seed


def _render_one(page, g, out_dir, log, gens, hist):
    gen = _choose_generator(gens, hist, g)
    seed = _new_seed(gen, hist)
    # не повторювати набір картинок: ні попереднього відео, ні минулого разу в цьому генераторі
    prev_img = {next((r.get("images") for r in reversed(hist["recent"]) if r.get("gen") == gen), None),
                hist["recent"][-1].get("images") if hist["recent"] else None} - {None}
    log(f"Генерую {gen} (seed {seed}) …")
    page.goto(f"{g['site']}/generators/{gen}?seed={seed}", wait_until="domcontentloaded")
    # кнопку шукаємо обома мовами — на випадок, якщо сайт таки відкрився іншою
    render_btn = page.get_by_role("button", name=re.compile(r"^\s*(Render video|Download video|Відрендерити відео|Завантажити відео)\s*$"))
    render_btn.wait_for(timeout=60000)
    try:  # банер cookie — відхиляємо
        page.get_by_role("button", name=re.compile(r"^\s*(Reject|Reject all|Decline|Відхилити)\s*$")).first.click(timeout=3000)
    except Exception:  # noqa: BLE001
        pass
    changed = _randomize(page, g)
    if changed:
        log("Налаштування: " + ", ".join(changed))
    img = _pick_images(page, g, avoid=prev_img, hist=hist)
    if img:
        log(f"Картинки: {img}")
    n_sec, n_fps = _num(g["length"]), _num(g["fps"])
    for options in ([f"{n_sec} s", f"{n_sec} с"], [g["resolution"]], [f"{n_fps} fps", f"{n_fps} кадр/с"]):
        loc = _exact(page, options[0])
        for alt in options[1:]:
            loc = loc.or_(_exact(page, alt))
        loc.first.click(timeout=10000)
    page.evaluate("window.__srBlob = null")
    render_btn.click()
    page.wait_for_function("window.__srBlob", timeout=g["render_timeout_sec"] * 1000, polling=1000)
    size = page.evaluate("window.__srBlob.size")
    name = f"{datetime.now():%Y%m%d-%H%M%S}_{gen}_{seed}.mp4"
    path = os.path.join(out_dir, name)
    step = 4 * 1024 * 1024
    with open(path, "wb") as f:
        for s in range(0, size, step):
            f.write(base64.b64decode(page.evaluate(READ_CHUNK, [s, min(s + step, size)])))
    desc = _read_description(page, g)
    if desc:
        with open(os.path.splitext(path)[0] + ".txt", "w", encoding="utf-8") as f:
            f.write(desc)
    log(f"Готово: {name} ({size / 1e6:.1f} МБ){' + опис' if desc else ' (опис не знайдено)'}")
    hist["recent"].append({"gen": gen, "seed": seed, "images": img, "file": name,
                           "settings": changed, "time": datetime.now().isoformat(timespec="seconds")})
    _save_hist(hist)
    return path


def login(cfg, log=print):
    """Звичайне (не автоматизоване) вікно Chrome з профілем скрипта — Google його пропускає."""
    g = settings(cfg)
    exe = _find_browser(g)
    if not exe:
        raise RuntimeError("Не знайшов Chrome. Встанови Google Chrome або вкажи browser_path у config.json.")
    log("Відкриваю Chrome. Увійди у свій акаунт Stimreel, потім закрий усе вікно Chrome.")
    subprocess.Popen([exe, f"--user-data-dir={PROFILE_DIR}", "--no-first-run",
                      "--no-default-browser-check", f"{g['site']}/login"])
    input("\n>>> Коли увійдеш у Stimreel і ЗАКРИЄШ вікно Chrome — натисни Enter тут... ")
    time.sleep(2)
    log("Сесію збережено.")


def _with_browser(g, fn, log):
    """Запустити Chrome з профілем скрипта (без вікна) і виконати fn(page)."""
    from playwright.sync_api import sync_playwright
    exe = _find_browser(g)
    if not exe:
        raise RuntimeError("Не знайшов Chrome. Встанови Google Chrome або вкажи browser_path у config.json.")
    with sync_playwright() as p:
        proc, port = _start_chrome(exe, g["headless"])
        browser = None
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            ctx.add_cookies([{"name": "NEXT_LOCALE", "value": g["lang"], "url": "https://stimreel.com"}])
            return fn(ctx.new_page())
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:  # noqa: BLE001
                pass
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()


def check_games(cfg, log=print):
    """Кнопка «перевірити зараз»: оновити список ігор із сайту і показати його."""
    g = settings(cfg)
    hist = _load_hist()
    before = list(hist["known"])
    log("Перевіряю сторінку Generators на сайті …")
    gens = _with_browser(g, lambda page: _generators(page, g, hist, log, force=True), log)
    new = [x for x in gens if x not in before]
    counts = {}
    for r in hist["recent"]:
        counts[r.get("gen")] = counts.get(r.get("gen"), 0) + 1
    log(f"Ігор на сайті: {len(gens)}")
    for x in gens:
        mark = "  НОВА" if (before and x in new) else ""
        log(f"  - {x}: згенеровано {counts.get(x, 0)} відео{mark}")
    if before and not new:
        log("Нових ігор немає.")
    if isinstance(g["generators"], list) and g["generators"]:
        log("Увага: у config.json задано свій список ігор — нові до нього самі не додаються.")
    return gens


def generate(cfg, count, out_dir, log=print):
    """Згенерувати count відео в out_dir. Повертає список шляхів."""
    from playwright.sync_api import sync_playwright

    g = settings(cfg)
    exe = _find_browser(g)
    if not exe:
        raise RuntimeError("Не знайшов Chrome. Встанови Google Chrome або вкажи browser_path у config.json.")
    made = []
    with sync_playwright() as p:
        for headless in ([True, False] if g["headless"] else [False]):
            proc = browser = None
            try:
                proc, port = _start_chrome(exe, headless)
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                ctx.add_init_script(HOOK)
                # мова сайту запам'ятовується в cookie NEXT_LOCALE — ставимо потрібну
                ctx.add_cookies([{"name": "NEXT_LOCALE", "value": g["lang"], "url": "https://stimreel.com"}])
                page = ctx.new_page()
                hist = _load_hist()
                gens = _generators(page, g, hist, log)
                while len(made) < count:
                    made.append(_render_one(page, g, out_dir, log, gens, hist))
            except Exception as e:  # noqa: BLE001
                log(f"Генерація не вдалася ({'без вікна' if headless else 'з вікном'}): {e}")
            finally:
                try:
                    if browser:
                        browser.close()
                except Exception:  # noqa: BLE001
                    pass
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except Exception:  # noqa: BLE001
                        proc.kill()
            if len(made) >= count:
                break
    return made
