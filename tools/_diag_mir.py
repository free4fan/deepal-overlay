#!/usr/bin/env python3
"""Diagnostic: why the mirror self-check fails on a screen — per pill,
observed vs mirror (w, h, fs, path, shape, fit branch)."""
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
s4_spec = importlib.util.spec_from_file_location("s4", Path(__file__).parent /
                                                 "step4_layout_audit.py")
s4 = importlib.util.module_from_spec(s4_spec)
s4_spec.loader.exec_module(s4)  # noqa: E402

screen = sys.argv[1] if len(sys.argv) > 1 else "mashina_top"
ww = "--word-wrap" in sys.argv
BASE = ROOT / "tools/golden" / sys.argv[2] if len([a for a in sys.argv[2:]
                                                   if a != "--word-wrap"]) > 1 \
    else ROOT / "tools/golden/pre_step4_96_7282"

pills = ds.load_screen(BASE / screen)


class Bag:
    d = 2.25


bag = Bag()
bag.align, bag.start_locked, bag.font_sp = ds.load_profile()
M.set_text_slopes(ds.build_slopes(pills))
specs = ds.scale(pills, 2.25)
runs = ds.run_screen(specs, bag, ww, frame1=False)

for p, s in zip(pills, specs):
    out, _t = runs[(s.x, s.y)]
    obs = p["pill"]
    n = p["node"]
    w, h, e = p.get("est", 0), n[2] - n[0], n[3] - n[1]
    est_px = s4.estimate_px(e if False else n[3] - n[1])
    close, lc, maxw = s4.sibling_facts(p, pills)
    stand, tall, wide, loose = s4.shape_classes(
        p.get("est", 0) or 0, n[2] - n[0], n[3] - n[1], est_px, close)
    ex = [n[0] + out["ddx"], n[1] + out["ddy"], out["width"], out["height"]]
    flag = ""
    for s_, o_, e_ in zip("xywh", ex, obs):
        if abs(o_ - e_) > 2:
            flag += s_
    if not flag:
        continue
    dev = " ".join("%s%+d" % (s_, e_ - o_) for s_, e_, o_ in zip("xywh", ex, obs))
    print("%-18s %r\n  obs=[%s]  mir=[%s]  dev: %s"
          % ((p.get("id") or "?")[:18], p["text"][:40],
             "[" + ", ".join(map(str, obs)) + "]",
             "[" + ", ".join(map(str, ex)) + "]", dev))
    print("  node=%s est=%d fsObs=%.2f fsMir=%.2f path=%s ml=%s "
          "stand/tall/wide/loose=%s/%s/%s/%s maxW=%d near-c=%s"
          % (n, p.get("est", 0), p["fsPx"], out["fs_px"], out["path"],
             out["multiline"], stand, tall, wide, loose, maxw, lc))
