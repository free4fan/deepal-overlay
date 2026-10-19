#!/usr/bin/env python3
"""golden_report.py — classify a golden diff into GEOMETRY vs ENVIRONMENT.

Runs `diff_golden.py --json` (or reads an existing report.json) and splits
every HARD signal into two buckets that have *different* meanings:

  GEOMETRY  = a node, or a pill RELATIVE TO ITS NODE, actually moved/resized.
              For a code change this is the real regression signal. For a
              dictionary/profile-only release it MUST be 0 (the runtime only
              reads sp+sl, untouched by a dictionary change).
  ENVIRONMENT = a pill/node (id,text) present in one run but not the other
              (NEW / GONE). Across a multi-day baseline->verify gap this is
              dominated by LIVE CONTENT churn: rotating promo banners, trip
              statistics, notification lists, tab counters. It is a data
              delta, NOT a layout regression, and cannot be driven to zero
              by our code.

Output: a per-screen breakdown + a top-line
  GEOMETRY DRIFT = N   (PASS if 0, else FAIL listing each)
  ENVIRONMENT CHURN = M (informational, each with a likely cause hint)

The GEOMETRY count is the gate that must stay 0 for step-3 (dictionary)
releases. The ENVIRONMENT count is reported, not gated.

Usage:
  python3 tools/golden_report.py <baseline_dir> <new_dir>
  python3 tools/golden_report.py --json <report.json>
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
TOOLS = HERE.parent      # tools/
REPO = TOOLS.parent      # repo root


def run_diff(base_dir, new_dir):
    out = Path("/tmp/opencode") / "golden_diff_report.json"
    subprocess.run([sys.executable, str(TOOLS / "diff_golden.py"),
                    base_dir, new_dir, "--json", str(out)], check=False)
    return json.loads(out.read_text(encoding="utf-8"))


def classify(report):
    geom, env = [], []
    for s, e in report.get("screens", {}).items():
        if "status" in e:
            continue
        for m in e.get("nodes_moved", []):
            rec = {"screen": s, "node": m.get("node"), "text": m.get("text", "")}
            if m.get("kind") == "MOVED":
                rec["delta(x,y,w,h)"] = m.get("d(x,y,w,h)")
                rec["was"] = m.get("was")
                rec["now"] = m.get("now")
                geom.append(rec)
            else:  # GONE
                rec["cause_hint"] = "node (id,text) absent from this run — " \
                                    "live content or navigation state"
                env.append(rec)
        for key, v in e.get("coverage_new", {}).items():
            drift = v.get("drift")
            if not drift:
                continue
            if drift.startswith("pill moved relative"):
                geom.append({"screen": s, "pill": key,
                             "drift": drift,
                             "rel_L_TR_B": v.get("rel_L_TR_B")})
            elif drift.startswith("NEW") or "GONE" in drift:
                hint = "NEW pill id+text" if drift.startswith("NEW") \
                    else "baseline pill id+text now absent"
                env.append({"screen": s, "pill": key,
                            "drift": drift, "cause_hint": hint})
    return geom, env


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--json":
        report = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    elif len(sys.argv) >= 3:
        report = run_diff(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)

    geom, env = classify(report)
    print("=" * 70)
    print("GOLDEN REPORT  (geometry = layout regression; environment = data)",
          )
    print("baseline = %s" % report.get("baseline"))
    print("new      = %s" % report.get("new"))
    print("=" * 70)

    print("\n## GEOMETRY DRIFT (real layout change) — must be 0 for a")
    print("##    dictionary/profile-only release")
    if geom:
        for g in geom:
            print("  - [%s] %s" % (g["screen"],
                                   g.get("drift") or
                                   ("NODE %s %r %s" % (
                                       g.get("node"), g.get("text"),
                                       g.get("delta(x,y,w,h)") or ""))))
    else:
        print("  (none)")

    print("\n## ENVIRONMENT CHURN (live content / navigation — informational)")
    print("##    %d entries" % len(env))
    by_screen = {}
    for e in env:
        by_screen.setdefault(e["screen"], []).append(e)
    for s in sorted(by_screen):
        print("  [%s] %d:" % (s, len(by_screen[s])))
        for e in by_screen[s][:12]:
            print("      - %s | %s" % (
                e.get("pill") or e.get("node"),
                (e.get("drift") or "")[:60]))
        if len(by_screen[s]) > 12:
            print("      + %d more" % (len(by_screen[s]) - 12))

    print("\n" + "=" * 70)
    verdict = "PASS" if not geom else "FAIL"
    print("GEOMETRY DRIFT  = %d   -> %s" % (len(geom),
          "PASS (0) — invariant holds" if not geom else
          "FAIL — %d layout regression(s)" % len(geom)))
    print("ENVIRONMENT     = %d   (informational; live content across dates)"
          % len(env))
    print("=" * 70)
    sys.exit(0 if not geom else 1)


if __name__ == "__main__":
    main()
