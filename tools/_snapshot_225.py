#!/usr/bin/env python3
"""2.25 self-diff harness for the dp refactor: snapshot every node's
computeLayout output at the BASE density (frame1=False, baseline build
v2.10.44 convention), then compare against a later run — the refactor
must be byte-invariant on the calibration density (DESIGN: «на d=2.25
механическая конверсия даёт 0 flips» — the self-diff makes that a
checked property, not a promise).

Usage: _snapshot_225.py --save FILE      # take a snapshot
        _snapshot_225.py FILE            # compare current vs FILE
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import density_sweep_mir as M  # noqa: E402
spec = importlib.util.spec_from_file_location("ds", ROOT / "density_sweep.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)  # noqa: E402

BASE = ROOT / "golden/pre_step4_96_7282"


def run_all():
    align, start_locked, font_sp = ds.load_profile()
    dump = {}
    for scr in sorted(d.name for d in BASE.iterdir() if d.is_dir()):
        pills = ds.load_screen(BASE / scr)
        M.set_text_slopes(ds.build_slopes(pills)[0])
        # T-36a iter 1: the per-node device wrap facts must be loaded for
        # BOTH snapshots (before/after), otherwise the "before" snapshot
        # (taken before the extension existed) diffs the extension itself
        # instead of the edit it guards.  DESIGN: «ИНВАРИАНТ self-diff для
        # Т-36a» — 141 clean + 5 known-bounded byte-identical, 25 boundary
        # may move.
        M.set_wrapped_lines(ds.build_lpin(pills))
        bag = ds._DenseBag(ds.BASE_D, align, start_locked, font_sp)
        specs = ds.scale(pills, ds.BASE_D)
        runs = ds.run_screen(specs, bag, False, frame1=False)
        for p in pills:
            key = "%s %s" % (scr, p["node"])
            out, trail = runs[(p["node"][0], p["node"][1])]
            dump[key] = {
                "out": {k: str(v) for k, v in sorted(out.items())},
                "conds": {e["cond"]: str(e["value"]) for e in trail},
            }
    return dump


if __name__ == "__main__":
    dump = run_all()
    if "--save" in sys.argv:
        fp = sys.argv[sys.argv.index("--save") + 1]
        with open(fp, "w") as f:
            json.dump(dump, f, ensure_ascii=False, indent=0, sort_keys=True)
        print("snapshot: %d nodes -> %s" % (len(dump), fp))
    else:
        old = json.loads(Path(sys.argv[1]).read_text())
        diff = 0
        for k in sorted(set(old) | set(dump)):
            o, n = old.get(k), dump.get(k)
            if o is None:
                print("NEW  %s" % k)
                diff += 1
                continue
            if n is None:
                print("GONE %s" % k)
                diff += 1
                continue
            for part in ("out", "conds"):
                for f, v in o[part].items():
                    nv = n[part].get(f, "<missing>")
                    if nv != v:
                        print("DIFF %s %s.%s: %s -> %s" % (k, part, f, v, nv))
                        diff += 1
                        break
                else:
                    continue
                break
        print("2.25 self-diff: %d/%d nodes invar%s"
              % (len(dump) - diff, len(dump), "iant ✓" if diff == 0
                 else "IANT ✗"))
        sys.exit(1 if diff else 0)
