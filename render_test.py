"""Тест через stimreel_gen: peg-drop і last-thread, 10 с, 1080p, з перемішуванням налаштувань."""
import os, sys, shutil, time
import stimreel_gen
os.makedirs("out", exist_ok=True)
ok = True
for gen in ("peg-drop", "last-thread"):
    cfg = {"generate": {"browser_path": shutil.which("google-chrome") or "", "length": 10, "generators": [gen],
                        "render_timeout_sec": 240}}
    t = time.time()
    made = stimreel_gen.generate(cfg, 1, "out", log=lambda m: print(m, flush=True))
    print(gen, "RESULT:", made, f"{time.time()-t:.0f}s", flush=True)
    ok = ok and bool(made)
sys.exit(0 if ok else 1)
