#!/usr/bin/env python3
"""Calibrate the density-sweep text model against the app's own output.

measure() must be multiplicative in fs (true for real fonts — advances
scale exactly linearly with the size; there is no advance hinting). The
per-char-class coefficients are not knowable offline: calibrate them on
the CLEAN equations from the baseline itself — PLAIN-shape single-line
pills where the width is TEXT-dominated (width == textArea + 2·padH with
textArea < nodeArea): there the equation is exact,
    measure(text, fs) = pill_w − 2·padH
and the observed fs is the app's own rendered font (the mirror self-check
already reproduces it). The grid search minimizes Σ(residual)².
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import density_sweep_mir as M  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "ds", Path(__file__).resolve().parent / "density_sweep.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)  # noqa: E402

s4_spec = importlib.util.spec_from_file_location(
    "s4", Path(__file__).resolve().parent / "step4_layout_audit.py")
s4 = importlib.util.module_from_spec(s4_spec)
s4_spec.loader.exec_module(s4)  # noqa: E402

BASE = ROOT / "tools/golden/pre_step4_96_7282"


def char_class(ch):
    o = ord(ch)
    if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
            or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF):
        return "cjk"
    if ch == ' ':
        return "sp"
    if ch.isalpha():
        return "alpha"
    if ch.isdigit():
        return "digit"
    return "punct"


def model_w(text, fs, coef):
    return fs * sum(coef[char_class(c)] for c in text)


def collect():
    """Clean text-dominated equations (text, fs, inner_width, vid)."""
    eqs = []
    for screen in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
        pills = ds.load_screen(BASE / screen)
        class Bag:
            d = 2.25
        bag = Bag()
        bag.align, bag.start_locked, bag.font_sp = ds.load_profile()
        specs = ds.scale(pills, 2.25)
        runs = ds.run_screen(specs, bag, False, frame1=False)
        for p, s in zip(pills, specs):
            out, _t = runs[(s.x, s.y)]
            if out["multiline"] or abs(out["width"] - p["pill"][2]) > 2:
                continue
            n = p["node"]
            est = p.get("est") or 0
            est_px = s4.estimate_px(n[3] - n[1])
            close, _lc, maxw = s4.sibling_facts(p, pills)
            stand, tall, wide, loose = s4.shape_classes(
                est, n[2] - n[0], n[3] - n[1], est_px, close)
            if stand or tall or wide or loose:
                continue                 # est-capped width, not clean
            node_area = min(n[2] - n[0], maxw - 2 * out["padh"])
            inner = p["pill"][2] - 2 * out["padh"]
            if inner <= node_area:
                continue                 # node-dominated: width capped,
                                         # the text equation is invisible
            eqs.append((p["text"], out["fs_px"], inner, p.get("id") or "?"))
    return eqs


def fit(coef, eqs):
    sse = sum((model_w(t, f, coef) - o) ** 2
              for t, f, o, _v in eqs)
    return sse, len(eqs)


def main():
    eqs = collect()
    print("calibrating on %d clean equations..." % len(eqs))
    best = None
    for a100 in range(40, 66):              # alpha 0.40..0.65
        for digit10 in (54, 55, 56, 57, 58):
            for sp100 in range(25, 31):
                for punct100 in range(30, 45, 2):
                    coef = {"cjk": 1.0, "alpha": a100 / 100.0,
                            "digit": digit10 / 100.0,
                            "sp": sp100 / 100.0,
                            "punct": punct100 / 100.0}
                    sse, n = fit(coef, eqs)
                    if n and (best is None or sse < best[1]):
                        best = (coef, sse, n)
    coef, sse, n = best
    print("best: %s  sse=%.1f n=%d rms=%.2f px"
          % (coef, sse, n, math.sqrt(sse / n)))
    rows = sorted(((abs(model_w(t, f, coef) - o), o,
                    model_w(t, f, coef) - o, v, t) for t, f, o, v in eqs),
                  reverse=True)
    print("worst residuals:")
    for _a, o, r, v, t in rows[:12]:
        print("  res=%6.2f obs=%5.0f model=%5.0f %-16s %r"
              % (r, o, o + r, v, t[:34]))
    print("n equations: %d" % len(eqs))


if __name__ == "__main__":
    main()
