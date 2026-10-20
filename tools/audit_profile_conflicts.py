#!/usr/bin/env python3
"""Audit view_profiles.json for conflicting alignment flags (step-4 pre-check).

Flags that carry ALIGNMENT meaning:
  sl:1          start-locked — CJK left-aligned in EVERY layout -> anchor LEFT
  g:"center"    center-gravity in all layouts               -> center ON node
  fw:1          full-width node                            -> geometry property
  p:<dp>        padStart (content inset)                   -> LEFT inset at x0+p*d
  mx:1          mixed gravity (step-3 explicit no-assert)  -> FALLBACK (both candidates)
  btn:1         dialog button (hug-stadium, gate F)         -> centered pill == button

A CONFLICT is an id where two flags pull the horizontal placement in
different directions, e.g. sl:1 + g:"center" (left vs center) — that id is
neither reliably one nor the other in a single profile, so neither flag may
win: it must fall back to the px-gates (the "mixed" default rule from the
step-4 design). decompile_ids.py is the upstream owner (it must classify such
ids as mx, not sl/g).

Output (stdout + optional --json):
  * the sl ∩ g:center set (hardest conflict: direct left-vs-center)
  * g:center ∩ p:<dp>  (center vs explicit left-inset)
  * g:center ∩ fw:1 and g:center ∩ mx:1 (informational)
  * btn ∩ everything (must be clean: a button is unambiguously centered)
  * a per-id verdict the layout code will use (CENTER / START / MIXED-fallback)
Exit code: 0 = no hard (left-vs-center) conflicts, 1 = some found (fix before
the frame-(1) window; they become a CHANGELOG debt line either way).
"""
import json
import sys
from pathlib import Path

PROFILE = Path(__file__).resolve().parent.parent / \
    "app/src/main/assets/view_profiles.json"


def flags_of(v):
    if isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict):
        return v[1]
    return {}


def sp_of(v):
    if isinstance(v, list) and len(v) > 0 and v[0] is not None:
        return v[0]
    return None


def main():
    out_json = (Path(sys.argv[sys.argv.index("--json") + 1])
                if "--json" in sys.argv else None)
    prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    rows, hard = [], []
    for k, v in prof.items():
        f = flags_of(v)
        sl = f.get("sl", 0) == 1
        g = f.get("g") == "center"
        fw = f.get("fw", 0) == 1
        mx = f.get("mx", 0) == 1
        btn = f.get("btn", 0) == 1
        p = f.get("p")
        if not (sl or g or fw or mx or btn or p is not None):
            continue
        conflict = None
        if sl and g:
            conflict = "sl+g:center (LEFT vs CENTER) — hard"
        elif g and p is not None and not mx and not btn:
            # btn ids carry g:center BY DESIGN (step 3: a centered label in a
            # hug-stadium button; the coverage model treats btn as centered),
            # so g+p on a pure (non-btn) id is the real center-vs-inset clash.
            conflict = "g:center+p=%sdp (CENTER vs LEFT-inset) — hard" % p
        elif g and mx:
            conflict = "g:center+mx (contradictory; mx must win → fallback)"
        # verdict the layout will take (precedence: mixed/mx, then btn,
        # then a single definite flag, else none → px-fallback)
        if mx:
            verdict = "MIXED→px-fallback"
        elif btn:
            verdict = "CENTER-btn(gate F)"
        elif sl and g:
            verdict = "CONFLICT→px-fallback"
        elif g and p is not None and not btn:
            verdict = "CONFLICT→px-fallback"
        elif g:
            verdict = "PROFILE-CENTER"
        elif sl:
            verdict = "PROFILE-START"
        else:
            verdict = "NONE→px-gates"
        rec = {"id": k, "sl": sl, "g": g, "fw": fw, "mx": mx, "btn": btn,
               "p": p, "sp": sp_of(v), "conflict": conflict, "verdict": verdict}
        rows.append(rec)
        if conflict and "hard" in conflict:
            hard.append(rec)

    print("PROFILE ALIGNMENT AUDIT  (%d ids, %d flagged)" %
          (len(prof), len(rows)))
    for tag, pred in [
            ("sl ∩ g:center (HARD left-vs-center)",
             lambda r: r["sl"] and r["g"]),
            ("g:center ∩ p:dp (HARD center-vs-inset)",
             lambda r: r["g"] and r["p"] is not None and not r["mx"]),
            ("g:center ∩ mx (mx must win → fallback)",
             lambda r: r["g"] and r["mx"]),
            ("btn ∩ others (g:center = by step-3 design; sl/p/mx would be a real conflict)",
             lambda r: r["btn"] and (r["sl"] or r["g"] or r["p"] is not None)),
    ]:
        hits = [r for r in rows if pred(r)]
        print("\n== %s : %d ==" % (tag, len(hits)))
        for r in hits[:40]:
            print("   %s  sl=%d g=%s fw=%d mx=%d btn=%d p=%s sp=%s" %
                  (r["id"], int(r["sl"]), r["g"], int(r["fw"]),
                   int(r["mx"]), int(r["btn"]), r["p"], r["sp"]))
    # verdict histogram
    from collections import Counter
    hist = Counter(r["verdict"] for r in rows)
    print("\n== verdict histogram ==")
    for k, c in sorted(hist.items()):
        print("   %-22s %d" % (k, c))
    print("\nHARD conflicts (must close before frame 1): %d" % len(hard))
    if out_json:
        out_json.write_text(json.dumps(
            {"ids": len(prof), "flagged": len(rows),
             "hard_conflicts": hard, "verdicts": [r for r in rows]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print("json ->", out_json)
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
