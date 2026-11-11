"""Тест: чи рендерить Stimreel на сервері GitHub (без входу)."""
import os, sys, shutil
import stimreel_gen
cfg = {"generate": {"browser_path": shutil.which("google-chrome") or "", "length": 10, "images": "random"}}
os.makedirs("out", exist_ok=True)
made = stimreel_gen.generate(cfg, 1, "out", log=lambda m: print(m, flush=True))
print("RESULT:", made)
sys.exit(0 if made else 1)
# run 2
