#!/usr/bin/env python3
"""Frame-(1) invariant checker — device-state tolerant (user decision 10-21).

The baseline is NOT a geometry oracle: it is a RECORD of the previous
build's behavior (and in exactly the 27 target pills that behavior is the
bug — left where the profile says center), plus capture-state artifacts
(scroll offset, top-row clipping, live content like «117天»). The check is
therefore per-pill and device-state tolerant, and the "expected" side is
recomputed deterministically (the step-4 mirror), never read off the
device:

  I1  non-target pills: node-relative geometry UNCHANGED (±2px) and pill
      size unchanged — frame 1 touches horizontal ddx only, and only for
      ids the px tree left at the left margin. Scroll offset between the
      two runs is irrelevant (relative geometry only).
  I2  target pills (a pill for which the mirror projects ddx_frame1 !=
      ddx_now, recomputed HERE from the baseline — same mirror as
      step4_layout_audit.py, nothing hardcoded): the new pill must sit at
      baseline-relative + (projected − baseline) — for that set the
      projection is node-centering, so I2 IS the "centered on its own
      node" invariant, with no pixel reference to any captured state.

Coverage of CJK by the pill is NOT re-judged here: run diff_golden.py and
read its per-pill `advisory` (the established model, rule 4) alongside.

Exclusions (reported as info, never compared):
  * a pill node clipped by a screen edge in EITHER run (the app truncates
    a clipped row's node.h -> est/geometry legitimately change: «Региста-
    тор/Передача файлов»);
  * live content drift: same id (or both idless) + node (w,h) ±8px + y
    within 24px but different text;
  * unpaired leftovers are listed for manual review (NEW/GONE).

Verdict: a screen is consistent iff it has 0 regressions (I1/I2 broken on
paired, non-clipped pills). A screen whose targets are simply not on its
current scroll state lists them as NOT-CAPTURED (info, no verdict) —
verify them in the canonical state.

Run: python3 tools/frame1_verify.py [baseline_dir] [new_dir] [screen ...]
"""
import json
import sys
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "s4", Path(__file__).with_name("step4_layout_audit.py"))
s4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s4)

TOL = 2
SCREEN_H = s4.SH  # 2142 at density 2.25


def load_pills(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def clipped(node):
    return node[1] <= 0 or node[3] >= SCREEN_H


def rel4(node, pill):
    pa = (pill[0], pill[1], pill[0] + pill[2], pill[1] + pill[3])
    return (pa[0] - node[0], pa[1] - node[1],
            node[2] - pa[2], node[3] - pa[3])


def same_w_h(a, b, tol=TOL):
    return (abs((a["node"][2] - a["node"][0])
                - (b["node"][2] - b["node"][0])) <= tol
            and abs((a["node"][3] - a["node"][1])
                    - (b["node"][3] - b["node"][1])) <= tol)


def targets_of(baseline_dir, run, profile_json):
    """Per baseline pill key (id, text): (ddx_now, ddx_frame1) from the SAME
    mirror as the audit — the single source of the target set."""
    pills = load_pills(Path(baseline_dir) / run / "pills.json")
    out = {}
    for p in pills:
        v = s4.profile_verdict(s4.flags_of(profile_json, p.get("id") or ""))
        d0, _p0 = s4.resolve_ddx(p, pills, v, profile=False)
        d1, _p1 = s4.resolve_ddx(p, pills, v, profile=True)
        out[(p.get("id") or "", p.get("text", ""))] = (d0, d1)
    return out, pills


def pair_runs(pb, pn):
    """Match new pills to baseline by (id, text) + node (w,h) ±TOL, nearest
    scroll-y first. Returns (shared, new_only, base_only)."""
    bykey = {}
    for q in pb:
        bykey.setdefault((q.get("id") or "", q.get("text", "")), []).append(q)
    shared, new_only, base_only = [], [], list(pb)
    for p in pn:
        # same (w,h) — except when the row is clipped at a screen edge in
        # EITHER run (the app truncates a clipped row's node.h, so 28px vs
        # 45px is the SAME pill in two clip states): pair it anyway, the
        # clip exclusion below keeps it out of the comparison.
        cands = [q for q in bykey.get((p.get("id") or "", p.get("text", "")), [])
                 if q in base_only
                 and (same_w_h(p, q)
                      or clipped(p["node"]) or clipped(q["node"]))]
        if not cands:
            new_only.append(p)
            continue
        cands.sort(key=lambda q: abs(q["node"][1] - p["node"][1]))
        q = cands[0]
        base_only.remove(q)
        shared.append((p, q))
    base_only.sort(key=lambda q: q["node"][1])
    return shared, new_only, base_only


def content_drift(new_only, base_only):
    """NEW/GONE pairs that are live content, not geometry."""
    pairs, nr, br = [], list(new_only), list(base_only)
    for p in list(nr):
        for q in br:
            if (p.get("id") == q.get("id")
                   or (not p.get("id") and not q.get("id"))) \
               and same_w_h(p, q, tol=8) \
               and abs(p["node"][1] - q["node"][1]) <= 24:
                pairs.append((p, q))
                nr.remove(p)
                br.remove(q)
                break
    return pairs, nr, br


def check_screen(run, baseline_dir, new_dir, profile_json):
    pb = load_pills(Path(baseline_dir) / run / "pills.json")
    pn = load_pills(Path(new_dir) / run / "pills.json")
    exp, _pills = targets_of(baseline_dir, run, profile_json)
    shared, new_only, base_only = pair_runs(pb, pn)
    drift, new_left, base_left = content_drift(new_only, base_only)

    verified, unchanged, regress, missing = [], 0, [], []
    nclip = 0
    in_new = set()
    for p, q in shared:
        rel_p, rel_q = rel4(p["node"], p["pill"]), rel4(q["node"], q["pill"])
        in_new.add((p.get("id") or "", p.get("text", "")))
        if clipped(p["node"]) or clipped(q["node"]):
            nclip += 1
            continue
        d0, d1 = exp.get((q.get("id") or "", q.get("text", "")), (0, 0))
        is_target = abs(d1 - d0) > TOL
        # frame 1 is HORIZONTAL-only: L += shift, R -= shift, T/B and pill
        # size are untouched.
        shift = d1 - d0
        exp_rel = (rel_q[0] + shift, rel_q[1], rel_q[2] - shift, rel_q[3])
        d = [rel_p[i] - exp_rel[i] for i in range(4)]
        size_ok = abs(p["pill"][2] - q["pill"][2]) <= TOL \
            and abs(p["pill"][3] - q["pill"][3]) <= TOL
        if max(abs(v) for v in d) <= TOL and size_ok:
            if is_target:
                verified.append((p, q, d0, d1))
            else:
                unchanged += 1
        else:
            regress.append("%s|%s@%s rel was %s now %s want %s (size d=%s) %s"
                           % (q.get("id"), q.get("text", "")[:14], q["key"],
                              list(rel_q), list(rel_p), list(exp_rel),
                              (p["pill"][2] - q["pill"][2],
                               p["pill"][3] - q["pill"][3]),
                              "[TARGET]" if is_target else ""))
    for q in pb:
        d0, d1 = exp.get((q.get("id") or "", q.get("text", "")), (0, 0))
        if abs(d1 - d0) <= TOL:
            continue
        k = (q.get("id") or "", q.get("text", ""))
        if k not in in_new:
            missing.append("%s target %s|%s@%s not captured (off-screen in "
                           "this scroll state? capture in canonical state)"
                           % ("clipped-in-baseline:" if clipped(q["node"]) else "",
                              q.get("id"), q.get("text", "")[:14], q["key"]))

    n_expect = sum(1 for (a, b) in exp.values() if abs(b - a) > TOL)
    ok = not regress
    print("  [%s] targets exp=%d verified=%d unchanged=%d | regression=%d "
          "clip-excl=%d drift=%d NEW=%d GONE=%d"
          % (run, n_expect, len(verified), unchanged, len(regress), nclip,
             len(drift), len(new_left), len(base_left)))
    for p, q, d0, d1a in verified:
        print("    ~ TARGET verified %s|%s ddx %d -> %d"
              % (p.get("id"), p.get("text", "")[:16], d0, d1a))
    for r in regress:
        print("    !! REGRESSION " + r)
    for m in missing:
        print("    ~ " + m)
    for p, q in drift:
        print("    ~ content-drift (live): %s %r -> %r"
              % (q.get("id") or "?", q.get("text", "")[:16], p.get("text", "")[:16]))
    for p in new_left:
        print("    ?? NEW (review) %s|%s @ %s" % (p.get("id"), p.get("text", "")[:14], p["key"]))
    for q in base_left:
        print("    ?? GONE (review) %s|%s @ %s" % (q.get("id"), q.get("text", "")[:14], q["key"]))
    return ok


def main():
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith("-")]
    base = Path(pos[0]) if len(pos) > 0 else Path("tools/golden/pre_step4_96_7282")
    new = Path(pos[1]) if len(pos) > 1 else Path("tools/golden/frame1_97_7282")
    only = pos[2:]
    profile = json.loads(Path("app/src/main/assets/view_profiles.json")
                         .read_text(encoding="utf-8"))
    runs = sorted(d.name for d in base.iterdir() if d.is_dir())
    if only:
        runs = [r for r in runs if r in only]
    allok = True
    print("frame-1 invariant check  baseline=%s new=%s" % (base, new))
    for run in runs:
        if not (new / run).exists():
            print("  [%s] (not captured yet)" % run)
            continue
        allok &= check_screen(run, base, new, profile)
    print("VERDICT: %s" % ("no regressions on the captured screens"
                            if allok else "REVIEW required"))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
