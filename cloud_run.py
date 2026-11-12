"""
cloud_run.py — повний цикл у хмарі GitHub: оновити статистику → згенерувати відео
на Stimreel (під акаунтом бота) → опублікувати в Instagram → записати журнал.

Секрети репозиторію (Settings → Secrets and variables → Actions):
  IG_TOKEN, IG_USER_ID            — доступ до Instagram (кладе cloud_keys.bat з ноутбука)
  STIMREEL_EMAIL, STIMREEL_PASSWORD — акаунт бота на Stimreel (вносиш сам)
Змінні запуску: COUNT (скільки відео), PUBLISH ("true"/"false").
"""
import base64
import json
import os
import shutil
import sys
import urllib.request

import ig_reels
import stats
import stimreel_gen

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def log(msg):
    print(msg, flush=True)


def _gh_api(method, path, body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
                                 method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def host_cover(path):
    """Покласти обкладинку в гілку covers публічного репозиторію й повернути пряме посилання на неї
    (Instagram бере обкладинку лише за публічним URL)."""
    if not (os.environ.get("GH_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        return None
    try:
        _gh_api("GET", "branches/covers")
    except Exception:  # noqa: BLE001  — гілки ще немає: створюємо від main
        sha = _gh_api("GET", "git/ref/heads/main")["object"]["sha"]
        _gh_api("POST", "git/refs", {"ref": "refs/heads/covers", "sha": sha})
    name = os.path.basename(path)
    with open(path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    _gh_api("PUT", f"contents/covers/{name}", {"message": f"cover {name}", "content": content, "branch": "covers"})
    return f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/covers/covers/{name}"


def main():
    count = max(1, min(10, int(os.environ.get("COUNT") or 1)))
    publish = (os.environ.get("PUBLISH") or "true").lower() != "false"
    token, ig_id = os.environ.get("IG_TOKEN"), os.environ.get("IG_USER_ID")
    email, password = os.environ.get("STIMREEL_EMAIL"), os.environ.get("STIMREEL_PASSWORD")

    cfg = {
        "access_token": token or "", "ig_user_id": ig_id or "",
        "api_version": "v27.0", "graph_host": "https://graph.facebook.com",
        "upload_host": "https://rupload.facebook.com", "share_to_feed": True,
        "default_caption": "Which one wins? 👀 #satisfying #oddlysatisfying #stimreel #reels",
        "generate": {"browser_path": shutil.which("google-chrome") or "", "length": "auto",
                     "resolution": "1080p", "fps": 30, "images": "random"},
    }

    if publish and not (token and ig_id):
        log("Немає секретів IG_TOKEN / IG_USER_ID — запусти cloud_keys.bat на ноутбуці. Публікацію пропущено.")
        publish = False

    if token and ig_id:
        try:
            stats.import_past(cfg, ig_reels.graph, log, os.path.join(HERE, "posted"))
            stats.refresh(cfg, ig_reels.graph, log, max_calls=200)
        except Exception as e:  # noqa: BLE001
            log(f"Статистику не оновлено: {e}")

    creds = (email, password) if email and password else None
    if not creds:
        log("Немає STIMREEL_EMAIL / STIMREEL_PASSWORD — відео буде зі знаком, без картинок і опису.")

    os.makedirs(OUT, exist_ok=True)
    made = stimreel_gen.generate(cfg, count, OUT, log=log, credentials=creds)
    if not made:
        log("Жодного відео не згенеровано.")
        return 1

    ok = 0
    for video in made:
        name = os.path.basename(video)
        txt = os.path.splitext(video)[0] + ".txt"
        caption = cfg["default_caption"]
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                caption = f.read().strip() or caption
        cover_url = None
        jpg = os.path.splitext(video)[0] + ".jpg"
        if os.path.exists(jpg):
            try:
                cover_url = host_cover(jpg)
                with urllib.request.urlopen(cover_url, timeout=30) as r:  # перевірка, що посилання відкривається
                    log(f"Обкладинка: {cover_url} ({len(r.read()) // 1024} КБ)")
            except Exception as e:  # noqa: BLE001
                log(f"Обкладинку не вдалося розмістити ({e}) — Instagram візьме кадр з відео.")
                cover_url = None
        if not publish:
            log(f"Згенеровано (без публікації): {name}")
            ok += 1
            continue
        try:
            media_id = ig_reels.publish_reel(cfg, video, caption, cover_url=cover_url)
            stats.record_post(name, media_id)
            log(f"Опубліковано: {name} → {media_id}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            log(f"ПОМИЛКА публікації {name}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
