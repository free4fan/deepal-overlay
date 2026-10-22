#!/usr/bin/env python3
"""T-36a iteration 2 BASELINE probe (10-22, contract rule 3: baseline
first, NO fix yet). Read-only, current mirror as-is.

For each residual W-class node (8: notifications x5, settings x3):
  * the width mechanism at 2.25: which term of the width equation wins
    (node_area vs text_area), the est-cap shape class, close_row /
    sibling facts, mirror width vs observed, fs (fit vs real);
  * char-class measure at the node's own fs vs the observed inner width
    (pw - 2*padh) — the pure model gap;
  * cross-screen WITNESSES: every pill on ANY screen with the same
    text (the double-pin candidates) with how the mirror renders it
    there (if a witness is clean and single-line with a winning text
    area -> it is a source of an S-slope for this text, verifiable by
    self-consistency on the target).
This is the data the per-(text, screen, node) scoped double pin would
consume; no model change.
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
    "notifications": [(0, 297), (92, 578), (92, 1253), (92, 1559),
                      (92, 1865)],
    "settings_car": [(388, 153), (0, 266), (92, 1360)],
}


def main():
    align, start_locked, font_sp = ds.load_profile()
    screens = {}
    for screen in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
        if not (BASE / screen / "pills.json").exists():
            continue
        pills = ds.load_screen(BASE / screen)
        slopes, _k = ds.build_slopes(pills)
        M.set_text_slopes(slopes)
        M.set_wrapped_lines(ds.build_lpin(pills))
        bag = ds._DenseBag(ds.BASE_D, align, start_locked, font_sp)
        specs = ds.scale(pills, ds.BASE_D)
        runs = ds.run_screen(specs, bag, False, frame1=False,
                             lpin=ds.build_lpin(pills))
        screens[screen] = (pills, runs, slopes, specs, bag)

    # cross-screen text index
    by_text = {}
    for screen, (pills, _r, _s, _sp, _b) in screens.items():
        for p in pills:
            t = p.get("text") or ""
            if t:
                by_text.setdefault(t, []).append((screen, p))

    # ---- part B: candidate self-consistency (contract form) --------------
    # per-text-in-screen S candidate (the only extension that leaves the
    # mirror's width equation and shape caps untouched): for each W
    # candidate text, the slope = inner/fsPx from its OWN pill, injected
    # into that screen's slope map; the FULL screen rerun verifies (the
    # contract: predicted(2.25) == observed(2.25) +/- 2px):
    #   * every target node of the text becomes clean (dev all <= 2),
    #   * NO other node of the screen moves (no propagation, lesson 0).
    def runcore(ctx, slopes_map):
        _pills, _runs, _slp, specs, bag = ctx
        M.set_text_slopes(slopes_map)
        return ds.run_screen(specs, bag, False, frame1=False,
                             lpin=ds.build_lpin(_pills))

    def dev_all(screen_pills, screen_runs):
        out = {}
        for p in screen_pills:
            k = (p["node"][0], p["node"][1])
            o, _t = screen_runs[k]
            obs = p["pill"]
            out[k] = (o["ddx"] + p["node"][0] - obs[0],
                      o["ddy"] + p["node"][1] - obs[1],
                      o["width"] - obs[2], o["height"] - obs[3])
        return out

    for screen in TARGETS:
        pills, runs, slopes, specs, bag = screens[screen]
        ctx = screens[screen]
        print("== SELF-CONSISTENCY %s ==" % screen)
        base_dev = dev_all(pills, runs)
        cands = {}
        for (tx, ty) in TARGETS[screen]:
            p = next(q for q in pills
                     if q["node"][0] == tx and q["node"][1] == ty)
            t = p.get("text") or ""
            fs = p.get("fsPx") or 0
            padh = max(4, M.ic(M.jf(fs * 0.4)))
            inner = p["pill"][2] - 2 * padh
            if t and fs:
                cands.setdefault(t, (p, inner, inner / fs))
        for t, (p, inner, slope) in cands.items():
            m = dict(slopes)
            was_pinned = t in m
            m[t] = slope
            new_runs = runcore(ctx, m)
            new_dev = dev_all(pills, new_runs)
            tgt = (p["node"][0], p["node"][1])
            movers = []
            for k in base_dev:
                bd, nd = base_dev[k], new_dev[k]
                moved = any(abs(bd[i] - nd[i]) > 2 for i in range(4))
                if moved:
                    movers.append(k)
            tgt_ok = all(abs(v) <= 2 for v in new_dev[tgt])
            others_clean = [k for k in movers if k != tgt]
            print("  cand %r fs=%.2f inner=%d slope=%.4f (already S: %s)"
                  % (t[:26], p.get("fsPx") or 0, inner, slope, was_pinned))
            print("    target dev now=%s -> %s  (%s)"
                  % (["%d" % v for v in base_dev[tgt]],
                     ["%d" % v for v in new_dev[tgt]],
                     "CLEAN" if tgt_ok else "FAIL"))
            others_clean = [(list(k), list(base_dev[k]), list(new_dev[k]))
                            for k in others_clean]
            print("    other movers: %s"
                  % ("NONE" if not others_clean else others_clean))
            M.set_text_slopes(slopes)  # restore after last cand
        print()

    for screen, keys in TARGETS.items():
        pills, runs, _s, _sp, _b = screens[screen]
        print("== %s ==" % screen)
        for (tx, ty) in keys:
            p = next(q for q in pills
                     if q["node"][0] == tx and q["node"][1] == ty)
            t = p.get("text") or ""
            n = p["node"]
            obs = p["pill"]
            fs = p.get("fsPx") or 0
            out, _trail = runs[(tx, ty)]
            padh = max(4, M.ic(M.jf(fs * 0.4)))
            padv = max(2, M.ic(M.jf(fs * 0.3)))
            lh = M.ic(M.jf(fs * 1.25))
            # the model's measure of the text at the node's own fit fs
            mfit = M.measure(t, out["fs_px"])
            mreal = M.measure(t, fs)
            inner = obs[2] - 2 * padh
            # witnesses: same text, other screens/nodes
            wit = [(s, q) for (s, q) in by_text.get(t, [])
                   if not (s == screen
                           and q["node"][0] == tx
                           and q["node"][1] == ty)]
            print("  node %s id=%r text=%r" % (list(n), p.get("id") or "?",
                                               t[:30]))
            print("    obs pill %dx%d @(%d,%d) | mirror w=%d h=%d "
                  "dev_x=%d dev_y=%d dev_w=%d dev_h=%d path=%s ml=%s "
                  "fs_fit=%.2f fs_real=%.2f"
                  % (obs[2], obs[3], obs[0], obs[1], out["width"],
                     out["height"], tx + out["ddx"] - obs[0],
                     ty + out["ddy"] - obs[1], out["width"] - obs[2],
                     out["height"] - obs[3], out["path"],
                     int(out["multiline"]), out["fs_px"], fs))
            print("    char-class W1: measure@fit=%.1f measure@real=%.1f "
                  "obs inner=%.1f (gap fit=%.1f real=%.1f)"
                  % (mfit, mreal, inner, mfit - inner, mreal - inner))
            # est/shape
            est = p.get("est") or 0
            est_px = ds.s4.estimate_px(n[3] - n[1])
            close, _lc, maxw = ds.s4.sibling_facts(p, pills)
            shape = ds.s4.shape_classes(est, n[2] - n[0], n[3] - n[1],
                                        est_px, close)
            print("    est=%d estPx=%.2f node=%dx%d shape(stand,tall,"
                  "wide,loose)=%s close_row=%s maxw=%.0f"
                  % (est, est_px, n[2] - n[0], n[3] - n[1], shape, close,
                     maxw))
            if wit:
                print("    WITNESSES (same text elsewhere): %d" % len(wit))
                for (s, q) in wit[:6]:
                    o2 = q["pill"]
                    print("      %-18s %s %dx%d obs=%dx%d dev-ish  text=%s"
                          % (s, list(q["node"]), o2[2], o2[3],
                             o2[2], o2[3], (q.get("id") or "")[:14]))
            else:
                print("    WITNESSES: NONE (text unique to this screen)")
        print()


if __name__ == "__main__":
    main()
