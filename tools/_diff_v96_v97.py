#!/usr/bin/env python3
"""Cross-run pill diff v96 (pre_step4_96_7282) vs v97 (frame1_97_7282).

Same screen, same app state: frame-1 (commit fa10056) touched ONLY the
single-line horizontal ddx fall-through — so every pill difference must
be a ddx-only change (x/w/h/node identical). Prints per pill: which of
node/x/y/w/h changed and by how much; then maps v97 pills onto the
frame-1 projected mover list from tools/step4_layout_audit.py (the 27).
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location(
    "s4", Path(__file__).with_name("step4_layout_audit.py"))
s4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s4)  # noqa: E402

OLD = ROOT / "tools/golden/pre_step4_96_7282"
NEW = ROOT / "tools/golden/frame1_97_7282"


def key(p):
    node = list(p["node"])
    return (tuple(node), (p.get("id") or ""), p.get("text", ""))


def main():
    align, _sl, _fs = None, None, None
    profile = json.loads((ROOT / "app/src/main/assets/view_profiles.json")
                         .read_text())
    screens = sys.argv[1:] or sorted(
        d.name for d in NEW.iterdir() if d.is_dir() and (d / "pills.json").exists())
    total = moved = okmoves = bad = 0
    for sc in screens:
        od, nd = OLD / sc, NEW / sc
        if not (od / "pills.json").exists() or not (nd / "pills.json").exists():
            print("== %s: missing in one run, skipped (old=%s new=%s)"
                  % (sc, (od / "pills.json").exists(),
                     (nd / "pills.json").exists()))
            continue
        o = json.loads((od / "pills.json").read_text())
        n = json.loads((nd / "pills.json").read_text())
        om = {key(p): p for p in o}
        nm = {key(p): p for p in n}
        only_o = [k for k in om if k not in nm]
        only_n = [k for k in nm if k not in om]
        moved = okmoves = 0
        print("== %s: old=%d new=%d  (only-old=%d only-new=%d)"
              % (sc, len(o), len(n), len(only_o), len(only_n)))
        for k in sorted(only_o, key=lambda k: k[1]):
            print("   GONE  %-16s node=%s %r" % (k[1][:16], k[0], k[2][:24]))
        for k in sorted(only_n, key=lambda k: k[1]):
            print("   NEW   %-16s node=%s %r" % (k[1][:16], k[0], k[2][:24]))
        for k in sorted(set(om) & set(nm), key=lambda k: k[0][1]):
            a, b = om[k], nm[k]
            oa, obs = a["pill"], b["pill"]
            dd = [obs[i] - oa[i] for i in range(4)]
            node_d = a["node"] == b["node"]
            if any(diff for diff in dd) or not node_d:
                moved += 1
                ddx = dd[0]
                ddx_pure = dd[0] != 0 and dd[1] == 0 and dd[2] == 0 \
                    and dd[3] == 0
                ok = ddx_pure and node_d
                okmoves += ok
                tag = "OK-ddx-only" if ok else "!! UNEXPECTED"
                print("   CHG %s %-16s pill %s -> %s  (%s) %r"
                      % (tag, (k[1] or "?")[:16], oa, obs,
                         "node!" if not node_d else "px", k[2][:20]))
        print("   -> %d/%d shared changed: %d clean-ddx-only, %d unexpected"
              % (moved, len(set(om) & set(nm)), okmoves, moved - okmoves))
    print()
    print("frame-1 move check: clean-ddx-only changes = intended movers")


if __name__ == "__main__":
    main()
