#!/usr/bin/env python3
"""T-36a iteration 3 BASELINE probe (10-23, contract rule 3: baseline
first, read-only, NO fix yet).

Residual 9 from iteration 2 (report mirror_cls):
  ddy-anchor x3:  explore tv_title [51,1482], my_tab txt_time [758,1081],
                  service_acc tv_charging_title [51,118] «Зарядка»
  stand x2 (W-cap, exposed by iter 2): notifications titleTv [0,297],
                  settings_car tvTopTitle [0,266]
Plus the stand mechanism needs the mirror's WIDTH-DECISION trail
(fit_w / text_cap / heading values) vs the observed inner width, and the
ddy nodes need the bottom/top anchoring arithmetic (is the observed pill
taller by exactly 2*7, i.e. the model's vertical centering on a shorter
pill? maxPillH inputs?).
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import density_sweep_mir as M
spec = importlib.util.spec_from_file_location("ds", ROOT / "density_sweep.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

BASE = ROOT / "golden/pre_step4_96_7282"

TARGETS = {
    "explore": [("51,1482" if False else 51, 1482)],
    "my_tab": [(758, 1081)],
    "service_acc": [(51, 118)],
    "notifications": [(0, 297)],
    "settings_car": [(0, 266)],
}


def main():
    align, start_locked, font_sp = ds.load_profile()
    for screen in sorted(TARGETS):
        pills = ds.load_screen(BASE / screen)
        slopes, _k = ds.build_slopes(pills)
        lpin = ds.build_lpin(pills)
        M.set_text_slopes(slopes)
        M.set_wrapped_lines(lpin)
        bag = ds._DenseBag(ds.BASE_D, align, start_locked, font_sp)
        specs = ds.scale(pills, ds.BASE_D)
        runs = ds.run_screen(specs, bag, False, frame1=False, lpin=lpin)
        print("== %s ==" % screen)
        for (tx, ty) in TARGETS[screen]:
            p = next(q for q in pills
                     if q["node"][0] == tx and q["node"][1] == ty)
            n = p["node"]
            obs = p["pill"]
            fs = p.get("fsPx") or 0
            out, trail = runs[(tx, ty)]
            padh = max(4, M.ic(M.jf(fs * 0.4)))
            padv = max(2, M.ic(M.jf(fs * 0.3)))
            lh = M.ic(M.jf(fs * 1.25))
            print("  node %s id=%r text=%r" % (list(n), p.get("id") or "?",
                                               (p.get("text") or "")[:26]))
            print("    obs pill %dx%d @(%d,%d)  mirror w=%d h=%d @(%d,%d)"
                  "  dev=(%d,%d,%d,%d) path=%s ml=%d fs_real=%.2f"
                  % (obs[2], obs[3], obs[0], obs[1],
                     out["width"], out["height"],
                     out["ddx"] + tx, out["ddy"] + ty,
                     out["ddx"] + tx + out["width"] - (obs[0] + obs[2]),
                     out["ddy"] + ty - obs[1],
                     out["width"] - obs[2], out["height"] - obs[3],
                     out["path"], int(out["multiline"]), fs))
            print("    vertical: obs top=%d bot=%d | mir top=%d bot=%d"
                  % (obs[1], obs[1] + obs[3],
                     out["ddy"] + ty,
                     out["ddy"] + ty + out["height"]))
            print("    node h=%d fs=%.2f lh=%d padh=%d padv=%d"
                  % (n[3] - n[1], fs, lh, padh, padv))
            # neighbor below (maxPillH input)
            below = [q for q in pills
                     if q["node"][1] > ty and q["node"][1] < ty + 300
                     and q["node"][0] < tx + 900 and q["node"][2] > tx]
            for q in below[:3]:
                qn = q["node"]
                print("      below: %s %dx%d @y=%d gap=%d text=%r"
                      % (q.get("id") or "?", qn[2] - qn[0],
                         qn[3] - qn[1], qn[1], qn[1] - (ty + (n[3] - n[1])),
                         (q.get("text") or "")[:20]))
            # width decision trail (for the stand nodes)
            for t in trail:
                c = t["cond"]
                if c in ("shape", "fontFit", "standHeading", "stand_cap",
                         "heading", "fitW", "lpin"):
                    print("    trail %-12s = %-28s %s"
                          % (c, str(t["value"])[:26], t["detail"][:60]))
        print()


if __name__ == "__main__":
    main()
