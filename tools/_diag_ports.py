#!/usr/bin/env python3
"""Diagnostic: full mirror output + trail for the suspected port?-nodes,
so the self-check classifier (wrap-model vs port) rests on data, not guesses."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import density_sweep_mir as M  # noqa: E402
spec = importlib.util.spec_from_file_location("ds", Path(__file__).parent /
                                               "density_sweep.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)  # noqa: E402

BASE = ROOT / "tools/golden/pre_step4_96_7282"
align, start_locked, font_sp = ds.load_profile()

WANT = [  # (screen, text prefix)
    ("notifications", "Обновление автомобиля"),
    ("notifications", "Для вашего Deepal S05 доступен новый вып"),
    ("notifications", "Обновление системы Deepal S05 завершено"),
    ("trip_info", "По сравнению с автомобилями"),
    ("trip_info", "Последние 30"),
]
for screen, prefix in WANT:
    pills = ds.load_screen(BASE / screen)
    M.set_text_slopes(ds.build_slopes(pills))
    bag = ds._DenseBag(2.25, align, start_locked, font_sp)
    runs = ds.run_screen(ds.scale(pills, 2.25), bag, True, frame1=False)
    for p in [q for q in pills if q.get("text", "").startswith(prefix)]:
        k = (p["node"][0], p["node"][1])
        out, trail = runs.get(k, (None, None))
        if out is None:
            continue
        ti = ds.trail_index(trail)
        print("== %s  %r" % (screen, p["text"][:44]))
        print("   node=%s est=%s fsPx=%s obs=%s"
              % (p["node"], p.get("est"), p.get("fsPx"), p["pill"]))
        print("   mir  x=%d y=%d w=%d h=%d  (ddx=%d ddy=%d fs=%.2f "
              "ml=%s wrap=%d prev=%s path=%s)"
              % (k[0] + out["ddx"], k[1] + out["ddy"], out["width"],
                 out["height"], out["ddx"], out["ddy"], out["fs_px"],
                 out["multiline"], out["wrap_lines"], bool(out["preview"]),
                 out["path"]))
        for c in ("shape", "fontFit", "band", "gateE", "gateF",
                  "frame1", "ddx", "ddy"):
            e = ti.get(c)
            if e is not None:
                print("   %-8s %s @ %s"
                      % (c, e["value"], str(e["detail"])[:92]))
        print()
