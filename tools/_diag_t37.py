#!/usr/bin/env python3
"""T-37 diagnostic (read-only mirror introspection).

Dumps per-node internals at d2.25 calibration (frame1=False) from the
CURRENT mirror (post-T-37 edit): t37 predicate + t37 target + width, so
the self-diff's 42 changed nodes can be classified against the exact
condition the edit implements — not against pixel-scan values that the
0.4-em-Cyrillic font model legitimately disagrees with.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import density_sweep_mir as M
spec = importlib.util.spec_from_file_location("ds", ROOT / "density_sweep.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

BASE = ROOT / "golden/pre_step4_96_7282"
align, sl, fs0 = ds.load_profile()
out = {}
for scr in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
    # FRESH load per screen — ds.scale mutates in place, a re-run on the
    # same objects would double-scale (this is the H2 artifact).
    pills = ds.load_screen(BASE / scr)
    M.set_text_slopes(ds.build_slopes(pills)[0])
    M.set_wrapped_lines(ds.build_lpin(pills))
    bag = ds._DenseBag(ds.BASE_D, align, sl, fs0)
    runs = ds.run_screen(ds.scale(pills, ds.BASE_D), bag, False, frame1=False)
    for p in pills:
        o, trail = runs[(p["node"][0], p["node"][1])]
        t37 = next((t for t in trail if t["cond"] == "t37"), None)
        t37_det = {}
        if t37:
            for tok in t37["detail"].split():
                if "=" not in tok:
                    continue
                a, b = tok.split("=", 1)
                try:
                    t37_det[a] = int(b)
                except ValueError:
                    pass
        out["%s %s" % (scr, p["node"])] = {
            "text": (p.get("text") or ""),
            "id": p.get("id") or "",
            "node_w": p["node"][2] - p["node"][0],
            "width": o["width"],
            "ddx": o["ddx"],
            "ddy": o["ddy"],
            "band": o.get("band"),
            "stadium": bool(t37["value"][1]) if t37 else None,
            "nodeWon": bool(t37["value"][0]) if t37 else None,
            "t37_nw": t37_det.get("nw"),
            "t37_ta": t37_det.get("ta"),
            "t37_est": t37_det.get("est"),
            "t37_path": o.get("path"),
            "t37_detail": t37["detail"] if t37 else "",
            "path": o.get("path"),
        }
# pull the pre-T-37 baseline width+ddx from the snapshot
old = json.load(open(ROOT / "golden/snap_preT37_225.json"))
for k, v in out.items():
    o = old.get(k)
    if o is None:
        continue
    v["old_w"] = int(o["out"]["width"])
    v["old_ddx"] = o["out"].get("ddx")
    v["old_band"] = o["out"].get("band")
    v["old_d"] = o["conds"].get("ddx")
json.dump(out, open("/tmp/opencode/t37_diag.json", "w"),
          ensure_ascii=False, indent=1, sort_keys=True)
print("nodes: %d -> /tmp/opencode/t37_diag.json" % len(out))
