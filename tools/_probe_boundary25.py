#!/usr/bin/env python3
"""T-36a baseline diagnostic (10-22): decompose the 25 model-boundary
nodes by mechanism BEFORE touching the model (contract rule 3: baseline
first, no fixes). Read-only: uses the committed mirror as-is.

Per node: dev vector (mirror@2.25 vs observed pill), pin kind (s/l/none),
mirror path + render state, and the dominant component:
  H  = |dev.h| >= line + 2*padv  -> LINE-COUNT issue (wrap decision /
       font-size model);
  W  = |dev.w| > 2 and not H    -> WIDTH issue (text-width model:
       unpinned slope / pin interval too wide);
  XY = |dev.x|/|dev.y| > 2       -> POSITIONING issue (ddx/ddy profile,
       not text model);
  MIX = >1 component.
Output: mechanism table + per-class counts. This drives WHICH data
extension closes the most of the 25 (S/L pins, align/profile, slopes).
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


def main():
    align, start_locked, font_sp = ds.load_profile()
    rep = json.loads(
        (ROOT / "golden/sweep_report_v96.json").read_text())
    rows = []
    per_screen_slopes = {}
    for screen in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
        if not (BASE / screen / "pills.json").exists():
            continue
        pills = ds.load_screen(BASE / screen)
        slopes, kinds = ds.build_slopes(pills)
        per_screen_slopes[screen] = (slopes, kinds)
        M.set_text_slopes(slopes)
        bag = ds._DenseBag(ds.BASE_D, align, start_locked, font_sp)
        runs = ds.run_screen(ds.scale(pills, ds.BASE_D), bag, False,
                             frame1=False)
        for p in pills:
            k = (p["node"][0], p["node"][1])
            out, _t = runs[k]
            obs = p["pill"]
            ex = [p["node"][0] + out["ddx"], p["node"][1] + out["ddy"],
                  out["width"], out["height"]]
            dev = {s: e - o for s, e, o in zip("xywh", ex, obs)}
            fs = p.get("fsPx") or 0
            lh = M.ic(M.jf(fs * 1.25)) if fs else 24
            padv = max(2, M.ic(M.jf(fs * 0.3))) if fs else 2
            if max(abs(v) for v in dev.values()) <= 2:
                continue          # clean: not a boundary candidate
            kind = kinds.get(p.get("text") or "")
            centering = out["path"] in ("band", "A", "B", "C1", "C2", "D",
                                        "E", "profile")
            obs_single = fs > 0 and p["pill"][2] > 0 and \
                p["pill"][3] < 2 * lh + 2 * padv
            ml_flip = obs_single != bool(out.get("multiline"))
            if centering or ml_flip:
                ok_x = abs(dev["x"]) <= abs(dev["w"]) / 2 + lh + 2
            else:
                ok_x = abs(dev["x"]) <= 2
            ok_h = abs(dev["h"]) <= lh + 2 * padv + 2
            cls_is_boundary = (not out.get("multiline")) and ok_x and ok_h
            # components
            H = abs(dev["h"]) > lh + 2
            W = abs(dev["w"]) > 2 and not H
            X = abs(dev["x"]) > 2 and not centering and not ml_flip
            Y = abs(dev["y"]) > 2
            if not (H or W or X or Y):
                comp = "EDGE(<=line)"
            elif H and (W or X or Y):
                comp = "H+MIX"
            elif H:
                comp = "H(lines)"
            elif W and (X or Y):
                comp = "W+MIX"
            elif W:
                comp = "W(width)"
            elif X or Y:
                comp = "XY(pos)"
            else:
                comp = "?"
            rows.append({
                "screen": screen, "id": p.get("id") or "?",
                "text": (p.get("text") or "")[:26],
                "pin": kind if kind else "none",
                "path": out["path"], "ml": bool(out.get("multiline")),
                "fs": round(fs / ds.BASE_D, 2),
                "dev": dev, "comp": comp,
                "boundary": cls_is_boundary,
                "centering": bool(centering), "ml_flip": ml_flip,
            })
    rows.sort(key=lambda r: (r["screen"], r["dev"].get("y", 0),
                             r["dev"].get("x", 0)))
    print("== 25+ boundary decomposition (mirror@2.25 vs observed) ==")
    hdr = "  %-18s %-18s %-10s %-6s %-6s %-4s %-4s %s"
    print(hdr % ("screen", "id", "comp", "pin", "path", "ml", "fsdp",
                 "dev x,y,w,h / text"))
    from collections import Counter
    c = Counter()
    for r in rows:
        c[r["comp"]] += 1
        mark = "" if r["boundary"] else "  <not-cls-boundary: port?>"
        print(hdr % (r["screen"][:18], (r["id"])[:18], r["comp"], r["pin"],
                     r["path"][:6], int(r["ml"]), r["fs"],
                     "%+d,%+d,%+d,%+d  %s%s" % (r["dev"]["x"],
                                                r["dev"]["y"],
                                                r["dev"]["w"],
                                                r["dev"]["h"],
                                                r["text"], mark)))
    print()
    for k, v in c.most_common():
        print("  %-12s %d" % (k, v))


if __name__ == "__main__":
    main()
