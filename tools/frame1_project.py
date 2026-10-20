#!/usr/bin/env python3
"""Frame-(1) layoutFromProfile projector — offline, no device.

Predicts EXACTLY which pills the step-4 profile wiring (PROFILE_CENTER
branch in computeLayout) will move, using the saved pre_step4 baseline
pills (the "before" side is observed, not re-simulated — the baseline was
produced by the current px-only runtime, so it IS the truth).

Model (mirrors the frame-(1) Java design, DESIGN.md «Шаг 4»):
  before (per observed pill):
    rel_L  = pill[0] - node[0]          (current ddx relative to its node)
  after  (PROFILE_CENTER ids only; all other ids: ddx unchanged by
           construction — the profile branch is absent for
           PROFILE_START/NONE/MIXED/PROFILE_BTN, those keep the exact
           px code path):
    guards   est > 0 && width > est  (else fall through to px = no move)
    center   ddx' = (nodeW - pillW) // 2   (Java int division)
    clamp x1 ddx' = max(ddx', -x)          (never cross the screen edge)
    clamp x2 if x + ddx' + pillW > x + maxW:
                    ddx' = int(maxW - pillW)
                    [maxW = max(48, screenWidth - x - 8): the profile
                     branch cannot widen the column any more than the
                     (A)-(E) centering branches can — same code shape]
    y unchanged; width/height unchanged (frame 1 = horizontal only)
  move iff |rel_L' - rel_L| > 2  (PILL-CHG threshold, diff_golden.py)

Category per moved pill (for the discrepancy list, frame-(2) planning):
  BAND       nav-band block (y > H-130) already centers these in the
             baseline, so ddx' == ddx is the EXPECTED invariant; a move
             here would mean the baseline did not uphold it -> look.
  (A)-agree  pill sits at the NODE CENTER within tol already: profile and
             px (A)-shape gate agree -> deleting (A) is safe for this id
             in frame 2.
  (A'-disagree) (A)-shape geometry, but the profile lands >2px off the
             current position: profile wins (frame-1 contract) — the
             delta goes into the discrepancy list.
  (D)-agree / (D'-disagree) same for the (D) empty-state shape.
  was-left   ddx ≈ 0 before: the px gates left it; the profile centers it
             -> the INTENDED frame-(1) movement, the evidence that
             layoutFromProfile does its job.
  was-other  neither left nor node-centered before (headerContentLeft
             inset / screen-mid centeredLabel): profile wins; document.

Exit is always 0 (projection, not a gate); the proof happens in the
phone window: hybrid after-capture, diff_golden vs pre_step4 must list
exactly the pills this tool lists, each with a verdict.
"""
import json
import sys
from pathlib import Path

TOL = 2            # PILL-CHG threshold (diff_golden.py)
EDGE_MARGIN = 8    # SCREEN_EDGE_MARGIN


def load_profile_flags(profile_path):
    """Mirror of TranslationService.loadViewProfiles flag routing:
    returns (clean_center_ids, flagged_ids). g+p (non-btn, non-mx) and
    sl+g and mx go to MIXED (px fallback) — NOT to clean center."""
    prof = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    center, flagged = set(), set()
    for k, v in prof.items():
        f = v[1] if isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict) else {}
        sl = f.get("sl", 0) == 1
        g = f.get("g") == "center"
        btn = f.get("btn", 0) == 1
        mx = f.get("mx", 0) == 1
        has_p = "p" in f
        if sl or g or btn or mx or has_p:
            flagged.add(k)
        clash = (sl and g) or (g and has_p and not mx and not btn)
        if clash or mx or btn:
            continue
        if g:
            center.add(k)
    return center, flagged


def predict(baseline_dir, profile_path, screen_w=960, screen_h=2142):
    center, flagged = load_profile_flags(profile_path)
    base = Path(baseline_dir)
    runs = sorted(d.name for d in base.iterdir()
                  if d.is_dir() and (d / "pills.json").exists())
    total = moves = center_seen = 0
    agg = {}

    def cat(name):
        agg[name] = agg.get(name, 0) + 1
        return name

    for run in runs:
        pills = json.loads((base / run / "pills.json").read_text())
        for p in pills:
            vid = p.get("id") or ""
            # pills.json coordinate convention (app golden dump + diff_golden):
            #   node = [x0, y0, x1, y1]  (a11y box, same as a11y.xml bounds)
            #   pill = [x, y, w, h]      (window rect)
            node = p["node"]
            pill = p["pill"]
            x0, y0, x1, y1 = node
            x, y = x0, y0
            w, h = x1 - x0, y1 - y0
            pw = pill[2]
            est = p.get("est", 0) or 0
            total += 1
            if vid not in center or est <= 0 or pw <= est:
                continue
            center_seen += 1
            rel_L = pill[0] - x
            maxW = max(48, screen_w - x - EDGE_MARGIN)
            ddx_c = (w - pw) // 2
            ddx_c = max(ddx_c, -x)
            if x + ddx_c + pw > x + maxW:
                ddx_c = int(maxW - pw)
            dL = ddx_c - rel_L
            if abs(dL) <= TOL:
                continue
            moves += 1
            in_band = y > screen_h - 130
            a_shape = (0 < y < 320 and 40 < x < screen_w * 0.6
                       and w > est * 4.5 and h < 74)
            d_shape = (x <= 30 and w >= screen_w * 0.95 and y > 340
                       and pw < w)
            if in_band:
                c = cat("BAND (nav-tab: expected centered)")
            elif a_shape and abs((w - pw) // 2 - rel_L) <= TOL:
                c = cat("(A)-agree: profile covers (A) -> frame2 deletable")
            elif a_shape:
                c = cat("(A'-disagree: profile vs (A) target)")
            elif d_shape and abs((w - pw) // 2 - rel_L) <= TOL:
                c = cat("(D)-agree: profile covers (D) -> frame4 deletable")
            elif d_shape:
                c = cat("(D'-disagree: profile vs (D) target)")
            elif abs(rel_L) <= TOL:
                c = cat("was-left -> centered (INTENDED frame-1 move)")
            else:
                c = cat("was-other -> centered (document)")
            print("[%s] %s id=%s est=%d node=(%d,%d,%d,%d) pillW=%d "
                  "ddx %d -> %d (%+d) %s  %r"
                  % (run, p.get("key"), vid, est, x, y, w, h, pw,
                     rel_L, ddx_c, dL, c, (p.get("text") or "")[:26]))

    print()
    print("== frame-(1) projection: %s ==" % baseline_dir)
    print("pills total=%d | PROFILE_CENTER ids=%d | flagged ids=%d | "
          "center-id pills seen (incl. non-movers)=%d"
          % (total, len(center), len(flagged), center_seen))
    print("pills that MOVE: %d" % moves)
    if agg:
        print("by category:")
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1]):
            print("   %-46s %d" % (k, v))
    else:
        print("(no moves — suspicious per the brief; an empty frame-1 "
              "proves nothing)")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else \
        "tools/golden/pre_step4_96_7282"
    prof = sys.argv[2] if len(sys.argv) > 2 else \
        "app/src/main/assets/view_profiles.json"
    predict(base, prof)
