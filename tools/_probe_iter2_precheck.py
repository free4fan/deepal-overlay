#!/usr/bin/env python3
"""T-36a iter 2 PRE-FIX verification (10-23). Read-only.

Confirms the proposed build_slopes pass-1 relaxation (allow S-pins for
wide/loose single-line nodes, with the SAME node_area est-cap the mirror's
width equation applies) adds pins for EXACTLY the 5 W-target texts and for
NO clean-node text across all 11 screens. This is the lesson-0
propagation check run BEFORE the edit: if any pin lands on a text that a
clean node carries, the relaxation is too broad.
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


def proposed_pass1(pills):
    """The proposed pass-1 S-pins (wide/loose relaxed), as a text set,
    plus the node keys that would supply them."""
    slopes, _ = ds.build_slopes(pills)
    new_pins = {}
    for p in pills:
        fs = p.get("fsPx") or 0
        n = p["node"]
        t = p.get("text") or ""
        if not fs or not t or p["pill"][2] <= 0:
            continue
        pw, ph = p["pill"][2], p["pill"][3]
        padh = max(4, M.ic(M.jf(fs * 0.4)))
        padv = max(2, M.ic(M.jf(fs * 0.3)))
        node_w, node_h = n[2] - n[0], n[3] - n[1]
        est = p.get("est") or 0
        est_px = ds.s4.estimate_px(node_h)
        close, _lc, maxw = ds.s4.sibling_facts(p, pills)
        stand, tall, wide, loose = ds.s4.shape_classes(
            est, node_w, node_h, est_px, close)
        if stand or tall:
            continue
        if not (wide or loose):
            continue                     # plain shapes already handled by pass 1
        if t in slopes:
            continue                     # already S-pinned (no change)
        node_area = min(node_w, maxw - 2 * padh)
        if wide:
            node_area = min(node_area, M.ic(M.jf(est * 2.2)))
        else:
            node_area = min(node_area, M.ic(M.jf(est * 1.35)) + padh)
        if ph < 2 * M.ic(M.jf(fs * 1.25)) + 2 * padv:
            inner = pw - 2 * padh
            if inner > node_area:
                new_pins.setdefault(t, []).append((n[0], n[1]))
    return new_pins, slopes


def main():
    align, start_locked, font_sp = ds.load_profile()
    grand = {}
    for screen in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
        if not (BASE / screen / "pills.json").exists():
            continue
        pills = ds.load_screen(BASE / screen)
        new_pins, cur = proposed_pass1(pills)
        if not new_pins:
            continue
        # which of the newly-pinned texts do CLEAN (non-problem) nodes carry?
        problems, _runs = ds.self_check(pills, ds._DenseBag(
            ds.BASE_D, align, start_locked, font_sp), False, frame1=False)
        clean_texts = set()
        for p in pills:
            k = (p["node"][0], p["node"][1])
            if k not in problems and p.get("text"):
                clean_texts.add(p["text"])
        risk = [t for t in new_pins if t in clean_texts]
        print("== %s ==" % screen)
        for t, nodes in new_pins.items():
            tag = "RISK(clean-node text)" if t in clean_texts else "ok"
            print("  +pin %-30r nodes=%s  %s" % (t[:30], nodes, tag))
        grand[screen] = (new_pins, risk)
    print()
    allpin = {}
    allrisk = set()
    for screen, (np_, risk) in grand.items():
        for t, nodes in np_.items():
            allpin.setdefault(t, []).append((screen, nodes))
        allrisk |= set(risk)
    print("TOTAL newly-pinned texts: %d" % len(allpin))
    for t, where in sorted(allpin.items()):
        print("  %-30r in %s" % (t[:30],
                                 [(s, n) for s, n in where]))
    print("RISK (clean-node shares a new-pinned text): %s"
          % ("NONE" if not allrisk else sorted(allrisk)))


if __name__ == "__main__":
    main()
