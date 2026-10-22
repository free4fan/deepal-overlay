#!/usr/bin/env python3
"""T-36a iteration 1 BASELINE probe (10-22, contract rule 3: baseline
first, NO fix yet). Read-only, current mirror as-is.

Step 1: capture the per-node L-pin facts straight from the dump (pill
height = L*lh + 2*padv on the DEVICE grid, L = floor quotient, L >= 2)
— the exact data the future model extension would consume.
Step 2: run the CURRENT model at 2.25.
Step 3: for every eligible node where the current model says single-line,
  re-derive the pinned branch manually with the mirror's OWN stock
  multiline formulas (fs = the device fs from the dump — real_fs at
  BASE is exactly that; h = L*lh + 2*padv; width = fit_w = out's;
  ddy = (node_h - h)/2 = the deep-pass formula with a same-row
  sibling, clamped by screen/max_pill for the expected rows) and report
  the predicted self-check deviation = the expected delta BEFORE any
  code change.
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


def capture_lpin(pills):
    """same arithmetic as the planned build_slopes pass 0 (contract
    form): device grid, floor quotient, L >= 2, int-exact or 1px
    residual; per-NODE key (base coords)."""
    lpin = {}
    for p in pills:
        fs = p.get("fsPx") or 0
        if not fs or not p.get("text"):
            continue
        n = p["node"]
        pw, ph = p["pill"][2], p["pill"][3]
        if pw <= 0:
            continue
        padv = max(2, M.ic(M.jf(fs * 0.3)))
        lh = M.ic(M.jf(fs * 1.25))
        if lh <= 0:
            continue
        L = (ph - 2 * padv) // lh
        if L < 2:
            continue
        if (ph - 2 * padv) % lh > 2:
            continue            # not on the device int grid: no fact
        lpin["%d,%d" % (n[0], n[1])] = min(L, 3)
    return lpin


def main():
    align, start_locked, font_sp = ds.load_profile()
    rows = []
    for screen in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
        if not (BASE / screen / "pills.json").exists():
            continue
        pills = ds.load_screen(BASE / screen)
        lpin = capture_lpin(pills)
        slopes, _kinds = ds.build_slopes(pills)
        M.set_text_slopes(slopes)
        bag = ds._DenseBag(ds.BASE_D, align, start_locked, font_sp)
        specs = ds.scale(pills, ds.BASE_D)
        runs = ds.run_screen(specs, bag, False, frame1=False)
        spec_by = {(s.x, s.y): s for s in specs}
        for p in pills:
            n = p["node"]
            key0 = "%d,%d" % (n[0], n[1])
            if key0 not in lpin:
                continue
            L = lpin[key0]
            fs = p["fsPx"]
            out, _trail = runs[(n[0], n[1])]
            s = spec_by[(n[0], n[1])]
            if bool(out["multiline"]):
                # already multiline in the model: the pin would fire on
                # an already-multiline state — out of contract scope
                print("%-18s %s ALREADY MULTILINE in model (L_cap=%d, "
                      "model wrap=%s, fs=%s): SKIP (contract scope = "
                      "single-line models only)"
                      % (screen, key0, L, out["wrap_lines"],
                         round(out["fs_px"], 2)))
                continue
            # ---- the pinned branch, stock formulas ----
            fs_pin = s.real_fs or fs              # device fs at this d
            lh_pin = M.ic(M.jf(fs_pin * 1.25))
            padv_pin = max(2, M.ic(M.jf(fs_pin * 0.3)))
            h = L * lh_pin + 2 * padv_pin
            # max_pill_h: a node below? re-derive from siblings (stock
            # compute_layout arithmetic)
            max_pill_h = M.JMAX
            gap_below = -1
            # the mirror's own stock constants at BASE_D (rp = ic(jf(dp*d)))
            same_row_dy = M.rp(M.SAME_ROW_DY_DP, ds.BASE_D)
            row_gap = M.rp(M.ROW_GAP_DP, ds.BASE_D)
            nb_px = M.rp(M.NEIGHBOR_MAX_DP, ds.BASE_D)
            for t in specs:
                if t is s:
                    continue
                if abs(t.y - s.y) > same_row_dy:
                    continue
                if t.y >= s.y + s.h + row_gap:
                    g = t.y - (s.y + s.h)
                    if gap_below < 0 or g < gap_below:
                        gap_below = g
                        max_pill_h = s.h + M.ic(M.jf(max(0, g) * 0.75))
            if max_pill_h < M.JMAX:
                h = min(h, max_pill_h)
            ddy = M.jdiv(s.h - h, 2)
            if ddy < 0:
                gap_above = M.JMAX
                for t in specs:
                    if t is s:
                        continue
                    tb = t.y + t.h
                    if tb > s.y or t.y <= s.y - nb_px:
                        continue
                    if t.x > s.x + out["width"] or t.x + t.w < s.x:
                        continue
                    g = s.y - tb
                    if g < gap_above:
                        gap_above = g
                if gap_above == M.JMAX or -ddy <= gap_above:
                    if s.y + ddy < 0:
                        ddy = -s.y
                    if ddy + h > (max_pill_h if max_pill_h < M.JMAX else M.JMAX):
                        ddy = (max_pill_h if max_pill_h < JMAX else M.JMAX) - h
                    if ddy > 0:
                        ddy = 0
            width = out["width"]     # fit_w unchanged (contract)
            ex = [n[0], n[1] + ddy, width, h]
            obs = p["pill"]
            dev = {k2: e - o for k2, e, o in zip("xywh", ex, obs)}
            clean = all(abs(v) <= 2 for v in dev.values())
            rows.append((screen, key0, p.get("id") or "?",
                         (p.get("text") or "")[:24], L, dev, clean))

    print()
    print("== predicted self-check @2.25 after the per-node L fact ==")
    print("  %-18s %-7s %-20s %-24s %-3s %-18s %s" % (
        "screen", "key0", "id", "text", "L", "dev x,y,w,h", "verdict"))
    n_ok = 0
    for r in rows:
        scr, key0, vid, txt, L, dev, clean = r
        n_ok += int(clean)
        print("  %-18s %-7s %-20s %-24s L=%d %s %s" % (
            scr, key0, vid[:20], txt, L,
            "%+d,%+d,%+d,%+d" % (dev["x"], dev["y"], dev["w"], dev["h"]),
            "CLEAN (dev<=2px)" if clean else "dev>2px — boundary stays"))
    print()
    print("eligible: %d; predicted CLEAN @2.25: %d; still dev>2: %d"
          % (len(rows), n_ok, len(rows) - n_ok))
    print("expected: 25 boundary -> %d ; 141 clean -> 141 (per-node "
          "scope, empty-map identity) ; 5 known -> 5"
          % (25 - len(rows)))


if __name__ == "__main__":
    main()
