"""Злити журнал цього запуску (new) з актуальним журналом у репозиторії (base) без конфліктів."""
import json
import sys


def key(r):
    return r.get("media_id") or r.get("file") or json.dumps(r, sort_keys=True)


def main(new_path, base_path):
    def load(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    new, base = load(new_path), load(base_path)
    out = dict(base)
    if (new.get("checked") or "") >= (base.get("checked") or ""):
        out["known"], out["checked"] = new.get("known", base.get("known", [])), new.get("checked", "")
    merged = {}
    for r in base.get("recent", []) + new.get("recent", []):
        k = key(r)
        # якщо запис уже є (напр. без media_id) — доповнюємо полями з новішої версії
        merged[k] = {**merged.get(k, {}), **r}
    # записи, що спершу були за file, а потім отримали media_id, — склеюємо
    by_file = {}
    for k, r in list(merged.items()):
        f = r.get("file")
        if f and f in by_file and by_file[f] != k:
            other = by_file[f]
            merged[other] = {**merged[other], **r}
            del merged[k]
        elif f:
            by_file[f] = k
    out["recent"] = sorted(merged.values(), key=lambda r: r.get("posted_at") or r.get("time") or "")[-1000:]
    with open(base_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
