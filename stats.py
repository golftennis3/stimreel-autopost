"""
stats.py — статистика опублікованих Reels і навчання вибору ігор/картинок.

* Після публікації в history.json записується media_id.
* Перед кожним post_now (і в stats.bat) скрипт забирає з Instagram цифри для відео,
  яким уже є 24 год (оновлює до 14 днів, потім цифри вважаються остаточними).
* Перегляди потребують дозволу instagram_manage_insights; без нього беремо лайки й коментарі.
* Вибір гри й набору картинок зважується за середнім результатом, але частина відео
  (explore, за замовчуванням 20%) і далі йде випадково — щоб пробувати нове.
"""
import json
import math
import os
import random
import re
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(HERE, "history.json")

DEFAULTS = {
    "learn": True,        # враховувати статистику при виборі
    "explore": 0.2,       # частка відео, які обираються без урахування статистики
    "min_posts": 5,       # з якої кількості відео з цифрами починати враховувати
    "strength": 1.5,      # наскільки сильно віддавати перевагу кращим (1 — м'яко, 3 — різко)
}

_warned = {"insights": False}


def stats_cfg(cfg):
    s = dict(DEFAULTS)
    s.update(cfg.get("stats") or {})
    return s


def _load():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            h = json.load(f)
    except Exception:  # noqa: BLE001
        h = {}
    h.setdefault("known", [])
    h.setdefault("checked", "")
    h.setdefault("recent", [])
    return h


def _save(h):
    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=1)
    os.replace(tmp, HISTORY_PATH)


def record_post(file_name, media_id):
    """Позначити в журналі, що відео опубліковане (щоб потім забрати статистику)."""
    h = _load()
    for r in reversed(h["recent"]):
        if r.get("file") == file_name:
            r["media_id"] = media_id
            r["posted_at"] = datetime.now().isoformat(timespec="seconds")
            break
    else:  # своє відео, не з генератора — теж запам'ятаємо, але без гри/картинок
        h["recent"].append({"file": file_name, "media_id": media_id,
                            "posted_at": datetime.now().isoformat(timespec="seconds")})
    _save(h)


def _fetch_one(cfg, graph, media_id):
    """Цифри одного Reel. Спершу перегляди (insights), інакше лайки/коментарі."""
    out = {}
    try:
        r = graph(cfg, "GET", f"{media_id}/insights",
                  metric="views,reach,likes,comments,shares,saved")
        for item in r.get("data", []):
            vals = item.get("values") or [{}]
            out[item["name"]] = vals[0].get("value", item.get("total_value", {}).get("value"))
    except RuntimeError as e:
        if not _warned["insights"] and ("permission" in str(e).lower() or "(#10)" in str(e)
                                         or "OAuth" in str(e)):
            _warned["insights"] = True
            out["_no_insights"] = True
    if "views" not in out:
        r = graph(cfg, "GET", media_id, fields="like_count,comments_count")
        out.setdefault("likes", r.get("like_count", 0))
        out.setdefault("comments", r.get("comments_count", 0))
    return out


def _parse_time(s):
    """ISO-час з журналу або з Instagram ("2026-11-11T20:17:32+0000") → місцевий час без зони."""
    s = s.replace("Z", "+00:00")
    if len(s) > 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    t = datetime.fromisoformat(s)
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _gen_from_file(name):
    m = re.match(r"^\d{8}-\d{6}_(.+)_(\d+)\.mp4$", name or "")
    return (m.group(1), int(m.group(2))) if m else (None, None)


def import_past(cfg, graph, log, posted_dir):
    """Підтягнути в журнал усі Reels акаунта й зіставити їх з іграми."""
    h = _load()
    have = {r.get("media_id") for r in h["recent"] if r.get("media_id")}
    by_file = {r.get("file"): r for r in h["recent"] if r.get("file")}
    known = list(h.get("known") or [])
    for r in h["recent"]:
        if r.get("gen") and r["gen"] not in known:
            known.append(r["gen"])

    # що лежить у posted: підписи (.txt) і час публікації (час переміщення файлу)
    captions, times = {}, []
    if os.path.isdir(posted_dir):
        for f in os.listdir(posted_dir):
            path = os.path.join(posted_dir, f)
            if f.lower().endswith(".txt"):
                try:
                    with open(path, encoding="utf-8") as fh:
                        captions[fh.read().strip()] = os.path.splitext(f)[0] + ".mp4"
                except Exception:  # noqa: BLE001
                    pass
            elif f.lower().endswith(".mp4"):
                times.append((datetime.fromtimestamp(os.path.getmtime(path)), f))

    media, after = [], None
    for _ in range(20):  # до 2000 публікацій
        params = {"fields": "id,caption,timestamp,media_product_type", "limit": 100}
        if after:
            params["after"] = after
        r = graph(cfg, "GET", f"{cfg['ig_user_id']}/media", **params)
        media += r.get("data", [])
        after = (r.get("paging") or {}).get("cursors", {}).get("after")
        if not (r.get("paging") or {}).get("next"):
            break

    added = matched = 0
    for m in media:
        if m.get("media_product_type") != "REELS" or m["id"] in have:
            continue
        cap = (m.get("caption") or "").strip()
        when = _parse_time(m["timestamp"])
        file = captions.get(cap)
        if not file and times:  # найближче за часом відео з posted (до 15 хв)
            t, f = min(times, key=lambda x: abs((x[0] - when).total_seconds()))
            if abs((t - when).total_seconds()) <= 900:
                file = f
        gen, seed = _gen_from_file(file)
        if not gen:  # за хештегом: #pegdrop → peg-drop
            tags = {t.lower() for t in re.findall(r"#(\w+)", cap)}
            gen = next((k for k in known if k.replace("-", "").lower() in tags), None)
        entry = by_file.get(file) if file else None
        if entry is None:
            entry = {"gen": gen, "seed": seed, "file": file, "images": None, "imported": True}
            h["recent"].append(entry)
        entry["media_id"] = m["id"]
        entry["posted_at"] = when.isoformat(timespec="seconds")
        added += 1
        matched += bool(gen)
    if added:
        h["recent"].sort(key=lambda r: r.get("posted_at") or r.get("time") or "")
        _save(h)
    log(f"Знайдено Reels в акаунті: {len(media)}. Нових у журналі: {added}, з них гру розпізнано: {matched}.")
    return h


def refresh(cfg, graph, log, max_calls=40):
    """Оновити статистику для опублікованих відео старших за 24 год (до 14 днів)."""
    h = _load()
    now = datetime.now()
    calls, updated, no_insights = 0, 0, False
    for r in reversed(h["recent"]):
        if calls >= max_calls:
            break
        mid, posted = r.get("media_id"), r.get("posted_at")
        if not mid or not posted:
            continue
        age = now - _parse_time(posted)
        if age < timedelta(hours=24) or (age > timedelta(days=15) and r.get("stats")):
            continue  # свіжі ще не показові; старі вже мають остаточні цифри
        last = r.get("stats_at")
        if last and now - datetime.fromisoformat(last) < timedelta(hours=20):
            continue
        try:
            st = _fetch_one(cfg, graph, mid)
            calls += 1
        except Exception as e:  # noqa: BLE001
            log(f"Статистика для {r.get('file')}: {e}")
            continue
        no_insights = no_insights or st.pop("_no_insights", False)
        r["stats"] = st
        r["stats_at"] = now.isoformat(timespec="seconds")
        updated += 1
    if updated:
        _save(h)
        log(f"Статистику оновлено для {updated} відео.")
    if no_insights:
        log("Перегляди недоступні (ключу бракує дозволу на статистику) — рахую за лайками й коментарями.")
    return h


def score(r):
    """Одна цифра «наскільки зайшло»: перегляди, а якщо їх немає — залученість."""
    st = r.get("stats") or {}
    if st.get("views") is not None:
        return float(st["views"]), "views"
    if st:
        return float(st.get("likes", 0) + 3 * st.get("comments", 0)
                     + 2 * st.get("shares", 0) + 2 * st.get("saved", 0)), "engagement"
    return None, None


def _table(h, key):
    """Середній результат за ключем (gen / images) з урахуванням лише одного типу цифр."""
    rows = [(r.get(key) or ("невідома гра" if key == "gen" else None), *score(r))
            for r in h["recent"] if r.get(key) or (key == "gen" and r.get("media_id"))]
    rows = [x for x in rows if x[0]]
    rows = [x for x in rows if x[1] is not None]
    if not rows:
        return {}, None, 0
    kind = "views" if any(k == "views" for _, _, k in rows) else "engagement"
    rows = [(name, s) for name, s, k in rows if k == kind]
    agg = {}
    for name, s in rows:
        n, tot = agg.get(name, (0, 0.0))
        agg[name] = (n + 1, tot + s)
    return agg, kind, len(rows)


def weights(cfg, h, key, names):
    """Множники ваги для кожного варіанту. 1.0 — нейтрально."""
    s = stats_cfg(cfg)
    if not s["learn"] or random.random() < s["explore"]:
        return {n: 1.0 for n in names}
    agg, _, total = _table(h, key)
    if total < s["min_posts"]:
        return {n: 1.0 for n in names}
    overall = sum(t for _, t in agg.values()) / sum(n for n, _ in agg.values()) or 1.0
    prior = 3  # «уявні» відео із середнім результатом — щоб 1 вдалий пост не перекосив усе
    out = {}
    for name in names:
        n, tot = agg.get(name, (0, 0.0))
        mean = (tot + prior * overall) / (n + prior)
        out[name] = max(0.3, min(3.0, (mean / overall) ** s["strength"]))
    return out


def report(cfg, log):
    h = _load()
    for key, title in (("gen", "Ігри"), ("images", "Набори картинок")):
        agg, kind, total = _table(h, key)
        if not agg:
            log(f"{title}: ще немає даних (потрібні опубліковані відео, старші за добу).")
            continue
        unit = "переглядів" if kind == "views" else "балів залученості"
        log(f"{title} (у середньому {unit}, за {total} відео):")
        for name, (n, tot) in sorted(agg.items(), key=lambda kv: -kv[1][1] / kv[1][0]):
            log(f"  {name:<20} {tot / n:>9.0f}   ({n} відео)")
    s = stats_cfg(cfg)
    posted = sum(1 for r in h["recent"] if r.get("media_id"))
    log(f"Reels у журналі: {posted}. Навчання: {'увімкнено' if s['learn'] else 'вимкнено'}, "
        f"пробувати нове: {int(s['explore'] * 100)}% відео, починає діяти з {s['min_posts']} відео з цифрами.")
