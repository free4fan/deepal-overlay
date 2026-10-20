#!/usr/bin/env python3
"""Step-4 layout audit — offline, no device (pre-frame-(1) gate, brief
§4.3: the offline run, the phone window becomes confirmation only).

One mirror of computeLayout's single-line placement
(InlineOverlayManager.java: nav-band block ~897, gates (A)/(B)/(C1/C2)/(D)/(E)
~940–1026, (F) ~1039–1097, shape classes ~565–591) produces:

 1. FRAME-1 PROJECTION — which pills the new PROFILE_CENTER branch moves,
    per pill: was -> now, the px place it came from, and a draft verdict.
    The "before" side is the OBSERVED pre_step4 baseline pills (the
    current runtime is the px truth — not re-simulated).
    Contract (DESIGN.md «Шаг 4»): the profile branch is entered from the
    single-line block with guards `est > 0 && width > est`, targets
    center-on-node with the SAME clamps the (A)-(E) branches use, and
    does not re-center a pill the nav-band block already centered
    (ddx != 0 guard). Everything else takes the px path unchanged.

 2. GATE COVERAGE for frames 2/3/4 — every baseline pill attributed to
    its px place (band/(A)/(B)/(C1)/(C2)/(D)/(E)/(F)/left/wrap) with its
    AlignSource verdict; per gate: the distinct ids it places and how
    many of its pills agree with the profile center target (gate
    redundant for that id) vs disagree (that id blocks deletion until
    decompile resolves the clash).

The px mirror is used only to EXPLAIN the observed baseline ddx
(±2px = PILL-CHG tolerance); unexplained pills are reported, never
guessed. `left` is the residual (no branch fired, ddx stayed 0) —
multiline pills land in `wrap` when their observed width equals their
column limit (the multiline width path) — the horizontal decision is
unobservable for them and they cannot be frame-1 movers (guard fails).

Run: python3 tools/step4_layout_audit.py [baseline_dir] [-v]
"""
import json
import sys
from pathlib import Path

TOL = 2            # PILL-CHG threshold (diff_golden.py)
EDGE_MARGIN = 8    # SCREEN_EDGE_MARGIN
ROW_GAP = 6
ROW_NEIGHBOR_MAX = 600
ROW_SAME_ROW_MAX_DY = 50
SW, SH, DENSITY = 960, 2142, 2.25
PAGE_HEADER_ID = "tvTopTitle"
FRAME_OF = {"(A)": 2, "(B)": 3, "(D)": 4}
GATE_ORDER = ["band", "(A)", "(B)", "(C1)", "(C2)", "(D)", "(E)", "(F)",
              "left", "wrap"]


def jdiv(a, b):
    """Java int division: truncate toward zero (Python // floors)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def center_target(w, pw, x):
    """ddx of every node-centering branch: center on the node, never cross
    the screen edge, never exceed the column limit (same code shape as
    the (A)-(E)/(F) ddx clamps and the frame-1 profile branch)."""
    ddx = jdiv(w - pw, 2)
    ddx = max(ddx, -x)
    maxW = max(48, SW - x - EDGE_MARGIN)
    if x + ddx + pw > x + maxW:
        ddx = int(maxW - pw)
    return ddx


def flags_of(profile, k):
    v = profile.get(k)
    f = v[1] if isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict) else {}
    return f


def profile_verdict(f):
    sl = f.get("sl", 0) == 1
    g = f.get("g") == "center"
    btn = f.get("btn", 0) == 1
    mx = f.get("mx", 0) == 1
    has_p = "p" in f
    if mx or (sl and g) or (g and has_p and not btn):
        return "MIXED"
    if btn:
        return "PROFILE_BTN"
    if g:
        return "PROFILE_CENTER"
    if sl:
        return "PROFILE_START"
    return "NONE"


def sibling_facts(pill, pills):
    x, y = pill["node"][0], pill["node"][1]
    h = pill["node"][3] - pill["node"][1]
    close_row = False
    left_clear = x
    near = -1
    for q in pills:
        if q is pill:
            continue
        qx, qy, qw = q["node"][0], q["node"][1], q["node"][2] - q["node"][0]
        dx = qx - x
        dy_ok = abs(qy - y) <= ROW_SAME_ROW_MAX_DY
        if 0 < dx < ROW_NEIGHBOR_MAX and dy_ok:
            close_row = True
            if near < 0 or dx < near:
                near = dx
        elif -ROW_NEIGHBOR_MAX < dx < 0 and dy_ok:
            left_clear = max(0, min(left_clear, x - (qx + qw)))
    maxw = max(48, SW - x - EDGE_MARGIN)
    if near > 48:
        maxw = min(maxw, near - ROW_GAP)
    return close_row, left_clear, near, maxw, h


def estimate_px(node_h):
    """estimateTextSize (TranslationService:861) at the device density —
    no profile involved, identical to the runtime for shape classes."""
    sp = max(10.0, min(node_h / DENSITY * (2.0 / 3.0), 24.0))
    return sp * DENSITY


def shape_classes(est, w, h, est_px, close_row):
    standalone = (not close_row and est > 0
                  and w > est * 2.5 and h > est_px * 1.8)
    tall_icon = (not close_row and not standalone and est > 0
                 and w <= est * 1.35 + 2
                 and est_px * 1.6 < h < est_px * 6)
    wide = (not close_row and not standalone and not tall_icon
            and est > 0 and w > est * 2.5)
    loose = (not close_row and not standalone and not tall_icon and not wide
             and est > 0 and w > est * 1.7 and h > est_px * 1.8)
    return standalone, tall_icon, wide, loose


def audit(baseline_dir, repo):
    profile = json.loads((Path(repo) / "app" / "src" / "main" / "assets"
                          / "view_profiles.json").read_text(encoding="utf-8"))
    base = Path(baseline_dir)
    runs = sorted(d.name for d in base.iterdir()
                  if d.is_dir() and (d / "pills.json").exists())

    total = moved = unexplained = 0
    verdict_hist = {}
    gate_pills = {g: 0 for g in GATE_ORDER}
    gate_ids = {g: set() for g in GATE_ORDER}
    movers = []
    bad_attr = []

    for run in runs:
        pills = json.loads((base / run / "pills.json").read_text())
        for p in pills:
            node = p["node"]
            pw, ph = p["pill"][2], p["pill"][3]
            x, y = node[0], node[1]
            w, h = node[2] - node[0], node[3] - node[1]
            est = p.get("est", 0) or 0
            rel_L = p["pill"][0] - x
            total += 1
            vid = p.get("id") or ""
            f = flags_of(profile, vid)
            v = profile_verdict(f)
            verdict_hist[v] = verdict_hist.get(v, 0) + 1
            est_px = estimate_px(h)
            close_row, left_clear, near, maxw, _ = sibling_facts(p, pills)
            standalone, tall_icon, _, loose = shape_classes(
                est, w, h, est_px, close_row)

            # ---- baseline attribution (explain the observed ddx) ----
            attr = None
            if y > SH - 130 and est > 0 and pw > est and not standalone \
                    and not tall_icon:
                overhang = jdiv(pw - est, 2)
                if overhang <= left_clear:
                    d = jdiv(est - pw, 2)
                    d = max(d, -x)
                    if x + d + pw > x + maxw:
                        d = int(maxw - pw)
                    if abs(rel_L - d) <= TOL:
                        attr = "band"
            # The (A)-(E) chain — the Java if/else-if structure, in order:
            # (toolbar || button || empty) -> center on node;
            # else headerContentLeft -> 24dp inset (54px @2.25);
            # else centeredLabel -> center on node.
            # (E)'s !wideRow is implied: wideRow needs w > est*2.5, (E) needs
            # w <= est*1.35+2 — mutually exclusive.
            if attr is None and est > 0 and not close_row and not tall_icon \
                    and not loose and pw > est:
                a = (not standalone and y < 320 and 40 < x < SW * 0.6
                     and w > est * 4.5 and h < 74 and v != "PROFILE_START")
                b = (x <= 60 and w >= SW * 0.83 and 96 <= h < 120
                     and w > est * 2.5 and v != "PROFILE_START")
                header_full = (standalone and x <= 30
                               and w >= SW * 0.95 and pw < w)
                c1 = header_full and vid == PAGE_HEADER_ID
                c2 = header_full and y < 340 and vid != PAGE_HEADER_ID
                d_ = header_full and y > 340 and vid != PAGE_HEADER_ID
                right_clear = SW - x - w - EDGE_MARGIN
                screen_mid = abs(x + w / 2.0 - SW / 2.0) <= 24
                balanced = (left_clear > 0 and right_clear > 0
                            and min(left_clear, right_clear)
                            >= 0.7 * max(left_clear, right_clear))
                e = (not standalone and w <= est * 1.35 + 2 and pw >= est
                     and screen_mid and balanced)
                cand_name = None
                cand_d = None
                if a or b or d_:
                    # the Java OR-branch: one shared action (center on node);
                    # attribute to the highest-priority predicate that fired
                    cand_name = "(A)" if a else ("(B)" if b else "(D)")
                    cand_d = center_target(w, pw, x)
                elif c1 or c2:
                    cand_name = "(C1)" if c1 else "(C2)"
                    cand_d = max(54, -x)  # (int)(24 * 2.25)
                    if x + cand_d + pw > x + maxw:
                        cand_d = int(maxw - pw)
                elif e:
                    cand_name = "(E)"
                    cand_d = center_target(w, pw, x)
                if cand_name is not None and abs(rel_L - cand_d) <= TOL:
                    attr = cand_name
            # (F) — a separate `if (ddx == 0 && ...)`, fires only when the
            # chain above left ddx at 0: the pill HUGS the node (pw == w).
            if attr is None and est > 0 and pw > est and x > 30 \
                    and SW * 0.28 < w < SW * 0.65 and 96 <= h <= 130 \
                    and w > est * 2.0 and abs(pw - w) <= TOL \
                    and not tall_icon:
                attr = "(F)"
            if attr is None:
                if pw >= maxw - 1 and ph > h * 1.3:
                    attr = "wrap"
                elif abs(rel_L) <= TOL:
                    attr = "left"
                else:
                    attr = "unexplained"
                    bad_attr.append(
                        "[{}] {} id={} ddx={} (not explained by the mirror)"
                        .format(run, p.get("key"), vid, rel_L))
                    unexplained += 1

            if attr in gate_pills:
                gate_pills[attr] += 1
                if vid:
                    gate_ids[attr].add(vid)

            # ---- frame-1 projection (PROFILE_CENTER only) ----
            if v == "PROFILE_CENTER" and est > 0 and pw > est \
                    and attr not in ("band", "(F)"):
                ft = center_target(w, pw, x)
                d = ft - rel_L
                if abs(d) > TOL:
                    moved += 1
                    # (A)/(B)/(D)/(E) and band pills have observed position ==
                    # the profile target by attribution construction, so the
                    # ONLY gated attributes a mover can come from are the
                    # header insets (C1)/(C2): the 24dp inset, not the node
                    # center. That is the documented frame-1 discrepancy:
                    # decompile says the header centers, the app keeps the
                    # left inset; the (C1) release resolves the id.
                    if attr in ("(C1)", "(C2)"):
                        verdict = ("KNOWN MISMATCH: app keeps the header "
                                   "left-inset ({}), profile says center -> "
                                   "stays put until the (C1) release; "
                                   "documented, does not block frames 2-4"
                                   ).format(attr)
                    elif attr in ("(A)", "(B)", "(D)", "(E)", "band"):
                        verdict = "BUG: gated pill projected as a mover — " \
                            "re-examine the mirror"
                    elif attr in ("left", "wrap"):
                        verdict = "INTENDED frame-1 move (px left it, profile centers)"
                    else:
                        verdict = "moved from {}: document".format(attr or "?")
                    movers.append("[{}] {} id={} est={} node=({},{},{},{}) "
                                  "pillW={} ddx {} -> {} ({:+d}) :: {}".format(
                                      run, p.get("key"), vid, est, x, y, w, h,
                                      pw, rel_L, ft, d, verdict))

    print("== step-4 layout audit (baseline {}) ==".format(baseline_dir))
    print("pills={} | verdicts: {}".format(total, verdict_hist))
    print("baseline attribution (the px runtime's decision, explained):")
    for g in GATE_ORDER:
        if gate_pills[g]:
            print("   {:<14} {:>3} pills  {:>3} ids".format(
                g + ":", gate_pills[g], len(gate_ids[g])))
    if bad_attr:
        print("   unexplained: {}".format(len(bad_attr)))
        for u in bad_attr:
            print("     " + u)

    print()
    print("frame-1 movers: {} (projected)".format(moved))
    for m in movers:
        print("   " + m)

    print()
    print("gate coverage -> frames 2/3/4:")
    for g in ("(A)", "(B)", "(D)"):
        ids = gate_ids[g]
        covered = {i for i in ids
                   if profile_verdict(flags_of(profile, i)) == "PROFILE_CENTER"}
        print("   gate {} -> frame {}: ids={} | PROFILE_CENTER ids={} "
              "| non-covered ids={}".format(
                  g, FRAME_OF[g], sorted(ids) if len(ids) <= 12 else
                  "%d total" % len(ids),
                  sorted(covered) if len(covered) <= 12 else
                  "%d total" % len(covered),
                  sorted(i for i in ids if i not in covered) or "none"))
    if unexplained == 0 and not movers:
        print("NOTE: zero movers AND zero unexplained — frame 1 would be a "
              "no-op; per the brief that proves nothing. Re-examine the "
              "profile-center set.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-v"]
    base = args[0] if args else "tools/golden/pre_step4_96_7282"
    audit(base, ".")
