"""Тест: повний рендер одного відео на сервері GitHub (без входу — зі знаком)."""
import os, sys, shutil
import stimreel_gen
cfg = {"generate": {"browser_path": shutil.which("google-chrome") or "", "length": 10, "images": "random"}}
os.makedirs("out", exist_ok=True)
made = stimreel_gen.generate(cfg, 3, "out", log=lambda m: print(m, flush=True))
print("RESULT:", made, [os.path.getsize(f) for f in made])
sys.exit(0 if made else 1)
