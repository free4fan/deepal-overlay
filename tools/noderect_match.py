#!/usr/bin/env python3
"""noderect_match.py — absolute node-rect match, baseline vs new.

For every translated node (id,text) present in BOTH runs, report whether
its a11y node rect is **byte-identical** or how far it moved (dx,dy, dw,dh).
This is an *absolute* check — it does not depend on comparing against a
baseline pill's node, so it is not fooled by the "uniform scroll offset"
ambiguity the way the delta diff can be: if the app's layout is truly
unchanged and both captures are at the same scroll state, every matched
rect is within a couple of px.

For a dictionary/profile-only release the expectation is: on each
correctly-captured screen, ALL matched nodes are within ±2px (i.e. the app
did not move a single translated view). A big spread means the two captures
are at different scroll states (a capture problem, not a layout regression)
— the per-node breakdown makes that visually obvious (uniform offset) vs
selective (a real layout change).

Usage:
  python3 tools/noderect_match.py <baseline_dir> <new_dir> [screen ...]
  python3 tools/noderect_match.py a b             # all common screens
  python3 tools/noderect_match.py a b trip_info   # one screen
"""
import json
import sys
from pathlib import Path

MOV_TOL = 2  # px within which we call a rect "identical"


def pills(fp):
    try:
        d = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return []
    return [p for p in d if p.get("node") and p.get("id")]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    base_dir, new_dir = Path(sys.argv[1]), Path(sys.argv[2])
    only = sys.argv[3:]
    screens = only if only else sorted(
        s.name for s in base_dir.iterdir() if s.is_dir())
    total_match = total_common = 0
    total_fail = 0
    for s in screens:
        b = {(p["id"], p["text"]): tuple(p["node"]) for p in
             pills(base_dir / s / "pills.json")}
        n = {}
        for p in pills(new_dir / s / "pills.json"):
            n.setdefault((p["id"], p["text"]), tuple(p["node"]))
        common = set(b) & set(n)
        if not common:
            print("[%s] no matched nodes" % s)
            continue
        moved = []
        match = 0
        for k in sorted(common):
            bn, nn = b[k], n[k]
            d = [nn[i] - bn[i] for i in range(4)]
            if max(abs(v) for v in d) <= MOV_TOL:
                match += 1
            else:
                moved.append((k, d))
        status = "MATCH" if not moved else "DRIFT"
        line = "[%s] %d/%d rects within ±%dpx  %s" % (
            s, match, len(common), MOV_TOL,
            "ALL-IDENTICAL" if not moved else
            "%d moved" % len(moved))
        print(line)
        for (i, t), d in moved[:8]:
            print("      - %-18s %-18s d(x,y,w,h)=%s" % (i, t[:18], d))
        if len(moved) > 8:
            print("      + %d more" % (len(moved) - 8))
        # detect uniform-offset (scroll) vs selective (layout)
        if moved:
            yds = [d[1] for _, d in moved]
            if max(yds) - min(yds) <= 4:
                print("      => uniform y-offset ~%dpx  (SCROLL STATE, not layout)"
                      % round(sum(yds) / len(yds)))
        total_match += match
        total_common += len(common)
        total_fail += len(moved)
    print("-" * 60)
    print("TOTAL: %d/%d node rects identical (tol ±%dpx), %d drifted"
          % (total_match, total_common, MOV_TOL, total_fail))
    print("A dictionary-only release should drive DRIFTED to 0 on every")
    print("correctly-captured screen (same scroll state both sides).")
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
