#!/usr/bin/env python3
"""
ig_reels.py — публікує відео з папки-черги в Instagram як Reels
через офіційний Instagram Graph API (Facebook Login, resumable upload).

Команди:
  python ig_reels.py check            перевірити токен і акаунт
  python ig_reels.py post             опублікувати одне наступне відео з черги
                                      (якщо черга майже порожня — спершу згенерувати на Stimreel)
  python ig_reels.py generate [N]     згенерувати N відео на Stimreel у чергу
  python ig_reels.py stats            оновити й показати статистику (що заходить краще)
  python ig_reels.py games            перевірити зараз, чи з'явилися нові ігри на сайті
  python ig_reels.py login            один раз увійти в акаунт Stimreel (рендер без водяного знака)
  python ig_reels.py cloud-setup      одноразово налаштувати хмарну публікацію через GitHub
  python ig_reels.py month [DAYS]     згенерувати відео на місяць, розписати й вивантажити в GitHub
  python ig_reels.py run              працювати постійно й публікувати в години з config.json
  python ig_reels.py token SHORT_TOKEN  обміняти короткий токен на довгий (60 днів) і знайти IG ID
  python ig_reels.py pagetoken          замінити токен користувача на безстроковий токен сторінки

Публікація — лише стандартна бібліотека Python 3.8+. Генерація — пакет playwright
і встановлений Microsoft Edge або Chrome. ffmpeg потрібен лише якщо відео не .mp4.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")


# ---------- утиліти ----------

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    if sys.stdout:  # під pythonw (планувальник) консолі немає
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001
            pass
    try:
        with open(os.path.join(HERE, "ig_reels.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def save_config(cfg):
    """Зберегти config.json, не записуючи туди службові шляхи, додані load_config."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    for k in ("cloud",):
        if k in cfg:
            raw[k] = cfg[k]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit("Немає config.json. Скопіюй config.example.json у config.json і заповни.")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("api_version", "v27.0")
    cfg.setdefault("graph_host", "https://graph.facebook.com")
    cfg.setdefault("upload_host", "https://rupload.facebook.com")
    cfg.setdefault("queue_dir", "queue")
    cfg.setdefault("posted_dir", "posted")
    cfg.setdefault("failed_dir", "failed")
    cfg.setdefault("default_caption", "")
    cfg.setdefault("share_to_feed", True)
    cfg.setdefault("post_times", ["18:00"])
    for k in ("queue_dir", "posted_dir", "failed_dir"):
        if not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(HERE, cfg[k])
        os.makedirs(cfg[k], exist_ok=True)
    return cfg


def http(method, url, params=None, headers=None, data=None, timeout=120):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} від {url.split('?')[0]}: {body}") from None
    return json.loads(body) if body else {}


def graph(cfg, method, path, **params):
    url = f"{cfg['graph_host']}/{cfg['api_version']}/{path.lstrip('/')}"
    params["access_token"] = cfg["access_token"]
    if method == "POST":
        data = urllib.parse.urlencode(params).encode()
        return http("POST", url, data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    return http("GET", url, params=params)


# ---------- черга ----------

def next_video(cfg):
    files = sorted(f for f in os.listdir(cfg["queue_dir"])
                   if f.lower().endswith(VIDEO_EXT) and not f.startswith("."))
    return os.path.join(cfg["queue_dir"], files[0]) if files else None


def caption_for(cfg, video):
    """Підпис: файл з тим самим ім'ям і .txt поруч з відео, інакше default_caption."""
    txt = os.path.splitext(video)[0] + ".txt"
    if os.path.exists(txt):
        with open(txt, encoding="utf-8") as f:
            return f.read().strip()
    return cfg["default_caption"]


def ensure_mp4(video):
    """Instagram хоче MP4 (H.264 + AAC). Не-mp4 конвертуємо через ffmpeg."""
    if video.lower().endswith(".mp4"):
        return video
    if not shutil.which("ffmpeg"):
        raise RuntimeError(f"{os.path.basename(video)} не .mp4, а ffmpeg не встановлено.")
    out = os.path.splitext(video)[0] + ".mp4"
    log(f"Конвертую {os.path.basename(video)} → mp4 …")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", video,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", out,
    ], check=True)
    os.remove(video)
    return out


def move_with_caption(video, dest_dir):
    for p in (video, os.path.splitext(video)[0] + ".txt", os.path.splitext(video)[0] + ".jpg"):
        if os.path.exists(p):
            shutil.move(p, os.path.join(dest_dir, os.path.basename(p)))


# ---------- публікація ----------

def publish_reel(cfg, video, caption, cover_url=None, host_video=None):
    """Опублікувати Reel. Спершу пряме завантаження файлу; якщо Instagram його не прийняв —
    (якщо передано host_video) викласти відео за публічним посиланням і дати Instagram забрати його самому.
    На кожному шляху: спершу з обкладинкою, потім без неї."""
    errors = []

    def attempt(url):
        if cover_url:
            try:
                return _publish_reel(cfg, video, caption, cover_url, url)
            except Exception as e:  # noqa: BLE001
                log(f"З обкладинкою не вийшло ({str(e)[:160]}) — пробую без неї.")
        return _publish_reel(cfg, video, caption, None, url)

    try:
        return attempt(None)
    except Exception as e:  # noqa: BLE001
        errors.append(e)
        if not host_video:
            raise
        log(f"Пряме завантаження не вдалося ({str(e)[:160]}) — пробую через публічне посилання.")
    url = host_video(video)
    log(f"Відео за посиланням: {url}")
    return attempt(url)


def _publish_reel(cfg, video, caption, cover_url=None, video_url=None):
    ig = cfg["ig_user_id"]
    size = os.path.getsize(video)

    # 1. Контейнер з resumable upload
    extra = {"cover_url": cover_url} if cover_url else {}
    c = graph(cfg, "POST", f"{ig}/media", media_type="REELS", upload_type="resumable",
              caption=caption, share_to_feed=str(cfg["share_to_feed"]).lower(), **extra)
    cid = c["id"]
    log(f"Контейнер {cid} створено, завантажую {size/1e6:.1f} МБ …")

    # 2. Завантаження: або сам файл, або посилання, з якого Instagram забере файл
    url = f"{cfg['upload_host']}/ig-api-upload/{cfg['api_version']}/{cid}"
    if video_url:
        up = http("POST", url, data=b"", timeout=600, headers={
            "Authorization": f"OAuth {cfg['access_token']}", "file_url": video_url})
    else:
        with open(video, "rb") as f:
            data = f.read()
        up = http("POST", url, data=data, timeout=600, headers={
            "Authorization": f"OAuth {cfg['access_token']}",
            "offset": "0",
            "file_size": str(size),
        })
    if not up.get("success", True):
        raise RuntimeError(f"Завантаження не вдалося: {up}")

    # 3. Чекаємо, поки Instagram обробить відео
    for _ in range(60):  # до ~10 хв
        st = graph(cfg, "GET", cid, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram відхилив відео: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("Обробка відео триває задовго, спробуй пізніше.")

    # 4. Публікація
    pub = graph(cfg, "POST", f"{ig}/media_publish", creation_id=cid)
    return pub["id"]


def queue_count(cfg):
    return sum(f.lower().endswith(VIDEO_EXT) for f in os.listdir(cfg["queue_dir"]))


def fill_queue(cfg):
    """Якщо в черзі мало відео — догенерувати на Stimreel."""
    gen_cfg = cfg.get("generate") or {}
    if gen_cfg.get("enabled") is False:
        return
    import stimreel_gen
    need = stimreel_gen.settings(cfg)["min_queue"] - queue_count(cfg)
    if need <= 0:
        return
    try:
        stimreel_gen.generate(cfg, need, cfg["queue_dir"], log=log)
    except Exception as e:  # noqa: BLE001
        log(f"Генерація не вдалася: {e}")


def cmd_generate(cfg, n):
    import stimreel_gen
    made = stimreel_gen.generate(cfg, n, cfg["queue_dir"], log=log)
    log(f"Згенеровано {len(made)} з {n}. У черзі: {queue_count(cfg)}")
    return len(made) == n


def host_cover_local(cfg, jpg):
    """Покласти обкладинку в гілку covers репозиторію GitHub через GitHub CLI (gh)
    і повернути публічне посилання. Якщо gh немає чи не залогінений — None."""
    import base64
    import cloud
    if not cloud.find_gh():
        return None
    c = cfg.get("cloud") or {}
    repo = c.get("repo") or (cloud.gh("api", "user", "--jq", ".login") + "/stimreel-autopost")
    if not cloud.gh("api", f"repos/{repo}/branches/covers", "--jq", ".name", check=False).strip() == "covers":
        sha = cloud.gh("api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha")
        cloud.gh("api", "-X", "POST", f"repos/{repo}/git/refs", "-f", "ref=refs/heads/covers", "-f", f"sha={sha}")
    name = os.path.basename(jpg)
    with open(jpg, "rb") as f:
        body = {"message": f"cover {name}", "content": base64.b64encode(f.read()).decode(), "branch": "covers"}
    cloud.gh("api", "-X", "PUT", f"repos/{repo}/contents/covers/{name}", "--input", "-", input_text=json.dumps(body))
    url = f"https://raw.githubusercontent.com/{repo}/covers/covers/{name}"
    for _ in range(6):  # дочекатися, поки посилання почне відкриватися
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                r.read(16)
            return url
        except Exception:  # noqa: BLE001
            time.sleep(5)
    return None


def cmd_post(cfg):
    try:  # оновити цифри з Instagram — щоб вибір гри враховував, що заходить
        import stats
        stats.refresh(cfg, graph, log)
    except Exception as e:  # noqa: BLE001
        log(f"Статистику не оновлено: {e}")
    fill_queue(cfg)
    video = next_video(cfg)
    if not video:
        log("Черга порожня — нічого публікувати.")
        return False
    name = os.path.basename(video)
    try:
        caption = caption_for(cfg, video)
        video = ensure_mp4(video)
        cover_url = None
        jpg = os.path.splitext(video)[0] + ".jpg"
        if os.path.exists(jpg) and (cfg.get("cover", True)):
            try:
                cover_url = host_cover_local(cfg, jpg)
                if cover_url:
                    log(f"Обкладинка: {cover_url}")
            except Exception as e:  # noqa: BLE001
                log(f"Обкладинку не вдалося розмістити ({str(e)[:150]}) — буде кадр з відео.")
        media_id = publish_reel(cfg, video, caption, cover_url=cover_url)
    except Exception as e:  # noqa: BLE001
        log(f"ПОМИЛКА з {name}: {e}")
        if os.path.exists(video):
            move_with_caption(video, cfg["failed_dir"])
        return False
    move_with_caption(video, cfg["posted_dir"])
    log(f"Опубліковано {name} → media id {media_id}")
    try:
        import stats
        stats.record_post(os.path.basename(video), media_id)
    except Exception as e:  # noqa: BLE001
        log(f"Не вдалося записати публікацію в журнал: {e}")
    return True


def cmd_run(cfg):
    times = sorted(cfg["post_times"])
    log(f"Режим розкладу. Публікую о {', '.join(times)}. Ctrl+C щоб зупинити.")
    while True:
        now = datetime.now()
        slots = []
        for t in times:
            h, m = map(int, t.split(":"))
            s = now.replace(hour=h, minute=m, second=0, microsecond=0)
            slots.append(s if s > now else s + timedelta(days=1))
        nxt = min(slots)
        log(f"Наступна публікація: {nxt:%Y-%m-%d %H:%M}")
        while datetime.now() < nxt:
            time.sleep(min(60, max(1, (nxt - datetime.now()).total_seconds())))
        cmd_post(load_config())  # перечитуємо конфіг — можна міняти без перезапуску


def cmd_check(cfg):
    me = graph(cfg, "GET", cfg["ig_user_id"], fields="username")
    log(f"Акаунт: @{me.get('username')} — токен працює.")
    try:
        lim = graph(cfg, "GET", f"{cfg['ig_user_id']}/content_publishing_limit",
                    fields="quota_usage,config")
        log(f"Ліміт публікацій: {lim}")
    except RuntimeError as e:
        log(f"Ліміт не вдалося прочитати: {e}")
    log(f"У черзі відео: {sum(f.lower().endswith(VIDEO_EXT) for f in os.listdir(cfg['queue_dir']))}")


def cmd_token(short_token):
    """Короткий токен → довгий (60 днів) + пошук IG Business ID через сторінки."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    host = raw.get("graph_host", "https://graph.facebook.com")
    ver = raw.get("api_version", "v25.0")
    r = http("GET", f"{host}/{ver}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": raw["app_id"],
        "client_secret": raw["app_secret"],
        "fb_exchange_token": short_token,
    })
    raw["access_token"] = r["access_token"]
    pages = http("GET", f"{host}/{ver}/me/accounts", params={
        "fields": "name,instagram_business_account{id,username}",
        "access_token": raw["access_token"],
    })
    for p in pages.get("data", []):
        iba = p.get("instagram_business_account")
        if iba:
            raw["ig_user_id"] = iba["id"]
            print(f"Знайдено @{iba.get('username')} (сторінка «{p['name']}»), ID {iba['id']}")
            break
    else:
        print("Не знайшов Instagram, прив'язаного до твоїх Facebook-сторінок. Див. README, крок 1.")
    raw["token_saved_at"] = datetime.now().strftime("%Y-%m-%d")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print("Довгий токен збережено в config.json (діє ~60 днів).")


def cmd_pagetoken():
    """Довгий токен користувача з config.json → безстроковий токен сторінки."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    host = raw.get("graph_host", "https://graph.facebook.com")
    ver = raw.get("api_version", "v27.0")
    pages = http("GET", f"{host}/{ver}/me/accounts", params={
        "fields": "name,access_token,instagram_business_account{id,username}",
        "access_token": raw["access_token"],
    })
    for p in pages.get("data", []):
        iba = p.get("instagram_business_account")
        if iba and (not raw.get("ig_user_id") or iba["id"] == raw["ig_user_id"]):
            raw["access_token"] = p["access_token"]
            raw["ig_user_id"] = iba["id"]
            raw["token_type"] = "page"
            raw.pop("token_saved_at", None)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            print(f"Готово: токен сторінки «{p['name']}» для @{iba.get('username')} збережено (безстроковий).")
            return
    sys.exit("Не знайшов сторінку з прив'язаним Instagram.")


def warn_token_age(cfg):
    if cfg.get("token_type") == "page":
        return
    saved = cfg.get("token_saved_at")
    if saved:
        age = (datetime.now() - datetime.strptime(saved, "%Y-%m-%d")).days
        if age >= 50:
            log(f"Увага: токену {age} днів, він скоро спливе (~60). Онови: див. README.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "post", "run", "token", "pagetoken", "times", "generate", "login",
                                                   "cloud-setup", "month", "games", "stats",
                                                   "cloud-keys"):
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "pagetoken":
        return cmd_pagetoken()
    if cmd == "times":  # для install.bat
        print(" ".join(load_config()["post_times"]))
        return
    if cmd == "token":
        if len(sys.argv) < 3:
            sys.exit("Використання: python ig_reels.py token КОРОТКИЙ_ТОКЕН")
        return cmd_token(sys.argv[2])
    cfg = load_config()
    warn_token_age(cfg)
    if cmd == "check":
        cmd_check(cfg)
    elif cmd == "post":
        sys.exit(0 if cmd_post(cfg) else 1)
    elif cmd == "cloud-setup":
        import cloud
        cloud.setup(cfg, save_config, log=log)
    elif cmd == "month":
        import cloud
        days = int(sys.argv[2]) if len(sys.argv) > 2 else None
        sys.exit(0 if cloud.month(cfg, days, log=log) else 1)
    elif cmd == "cloud-keys":
        import cloud
        repo = (cfg.get("cloud") or {}).get("repo") or (cloud.gh("api", "user", "--jq", ".login") + "/stimreel-autopost")
        cloud.gh("secret", "set", "IG_TOKEN", "--repo", repo, input_text=cfg["access_token"])
        cloud.gh("secret", "set", "IG_USER_ID", "--repo", repo, input_text=str(cfg["ig_user_id"]))
        log(f"Ключ Instagram збережено в секретах {repo}. Ніде не показується.")
    elif cmd == "stats":
        import stats
        try:
            stats.import_past(cfg, graph, log, cfg["posted_dir"])
        except Exception as e:  # noqa: BLE001
            log(f"Не вдалося підтягнути старі Reels: {e}")
        stats.refresh(cfg, graph, log, max_calls=500)
        stats.report(cfg, log)
    elif cmd == "games":
        import stimreel_gen
        stimreel_gen.check_games(cfg, log=log)
    elif cmd == "login":
        import stimreel_gen
        stimreel_gen.login(cfg, log=log)
    elif cmd == "generate":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        sys.exit(0 if cmd_generate(cfg, n) else 1)
    elif cmd == "run":
        try:
            cmd_run(cfg)
        except KeyboardInterrupt:
            log("Зупинено.")


if __name__ == "__main__":
    main()
