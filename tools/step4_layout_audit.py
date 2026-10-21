#!/usr/bin/env python3
"""Step-4 layout audit — offline, no device (pre-frame-(1) gate, brief
§4.3: the offline run, the phone window becomes confirmation only).

ONE mirror, `resolve_ddx()`, of computeLayout's full single-line HORIZONTAL
decision (InlineOverlayManager.java: nav-band block ~897, gates
(A)/(B)/(C1/C2)/(D)/(E) ~931–1027, (F) ~1039–1097, shape classes
~565–591, constants as in the Java). It takes a pill + the screen's pill
list (pills.json IS the spec list: every CJK node gets a pill) and returns
the ddx the tree picks plus the path name that decided it.

  profile=False  -> the CURRENT runtime (baseline behavior)
  profile=True   -> the FRAME-(1) wiring: the profile branch is a
                    FALL-THROUGH centerer at the END of the !multiline
                    horizontal block (exactly where the Java frame-(1)
                    release will place it). It claims a pill only when no
                    px gate fired (ddx is still the left default 0), the id
                    is unambiguously center-aligned, and width > est.
                    By construction the gate-placed pills are untouched —
                    verified on the canonical set: all 27 projected movers
                    come from path 'none' — including the full-width page
                    headers, which the (C1)/(C2)/(D) gates still carry at
                    their left-inset / empty-center until that decision's
                    own release (force-centering a 960px header would
                    expose CJK — rule 4).
                    No shape class guards the profile branch: the id flag
                    IS the stronger claim (a grid label that is g:center in
                    every layout centers even if looseRow — the shape
                    classes are heuristic guesses the profile replaces;
                    that is the step-4 mechanism).
                    PROFILE_START keeps the ddx-0 path (what isStartLocked
                    already does); PROFILE_BTN is claimed by (F)'s own
                    block, not by the centering branch (btn semantics
                    differ: full-button width, est font, stadium);
                    MIXED/NONE take the exact px tree.

Outputs:
  * baseline attribution: the path that decided each observed pill's ddx —
    a MIRROR SELF-TEST: every non-claimer single-line pill must match the
    observed ddx within PILL-CHG tolerance or it is reported (never a
    silent guess).
  * frame-(1) projection: per pill, ddx profile=True vs observed; movers
    (|delta| > 2px) with a draft verdict. Per the review's lock 2.1 this is
    the discrepancy list that must close before frame (2).
  * gate coverage: per gate (A)/(B)/(D), the distinct ids the baseline
    placed through it (empty = the frame's deletion is provable by an
    empty diff on the canonical set).

Multiline pills are out of the tree (the profile branch sits inside the
!multiline block; frame 1 changes horizontal ddx only, never the wrap),
so they never move — flagged as `wrap` and checked as ddx==0.

Run: python3 tools/step4_layout_audit.py [baseline_dir]
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
FRAME_OF = {"A": 2, "B": 3, "D": 4}
GATE_ORDER = ["profile(n/a)", "band", "A", "B", "C1", "C2", "D", "E", "F",
              "none", "wrap"]


def jdiv(a, b):
    """Java int division: truncate toward zero (Python // floors)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def clamp_center(w, pw, x):
    """Every node-centering ddx: center on node, keep on screen, keep in
    the column (the identical clamp trio of (A)/(B)/(D)/(E)/(F) and the
    frame-1 profile branch)."""
    ddx = jdiv(w - pw, 2)
    ddx = max(ddx, -x)
    maxw = max(48, SW - x - EDGE_MARGIN)
    if x + ddx + pw > x + maxw:
        ddx = int(maxw - pw)
    return ddx


def flags_of(profile, k):
    v = profile.get(k)
    return v[1] if isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict) else {}


def profile_verdict(f):
    sl = f.get("sl", 0) == 1
    g = f.get("g") == "center"
    btn = f.get("btn", 0) == 1
    mx = f.get("mx", 0) == 1
    has_p = "p" in f
    if mx or (sl and g) or (g and has_p and not btn):
        return "MIXED"          # clash (sl+g, g+p non-btn) or explicit mx
    if btn:
        return "PROFILE_BTN"
    if g:
        return "PROFILE_CENTER"
    if sl:
        return "PROFILE_START"
    return "NONE"


def sibling_facts(pill, pills):
    x, y = pill["node"][0], pill["node"][1]
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
    return close_row, left_clear, maxw


def estimate_px(node_h):
    """estimateTextSize (TranslationService:861) at device density —
    profile-free, identical to the runtime for the shape classes."""
    sp = max(10.0, min(node_h / DENSITY * (2.0 / 3.0), 24.0))
    return sp * DENSITY


def shape_classes(est, w, h, est_px, close_row):
    standalone = (not close_row and est > 0
                  and w > est * 2.5 and h > est_px * 1.8)
    tall_icon = (not close_row and not standalone and est > 0
                 and w <= est * 1.35 + 2
                 and est_px * 1.6 < h < est_px * 6)
    # wide/loose are computed but only used via their absence; keep names
    wide = (not close_row and not standalone and not tall_icon
            and est > 0 and w > est * 2.5)
    loose = (not close_row and not standalone and not tall_icon and not wide
             and est > 0 and w > est * 1.7 and h > est_px * 1.8)
    return standalone, tall_icon, wide, loose


def resolve_ddx(p, pills, v, profile):
    """The full single-line horizontal ddx tree. Returns (ddx, path).
    path: 'profile' | 'band' | 'A' | 'B' | 'C1' | 'C2' | 'D' | 'E' | 'F'
    | 'none' (no branch fired, ddx stayed 0)."""
    node = p["node"]
    x, y = node[0], node[1]
    w, h = node[2] - node[0], node[3] - node[1]
    pw = p["pill"][2]
    est = p.get("est", 0) or 0
    est_px = estimate_px(h)
    close_row, left_clear, maxw = sibling_facts(p, pills)
    standalone, tall_icon, _wide, loose = shape_classes(
        est, w, h, est_px, close_row)
    start_locked = v == "PROFILE_START"
    # headerFullRow hoisted: (C)/(D) use it in the chain below AND the
    # frame-1 profile branch uses it as its exclusion (a full-width
    # standalone header keeps the (C1)/(C2) left-inset / (D) center
    # semantics until that decision's own release — never the profile).
    header_full = (standalone and x <= 30
                   and w >= SW * 0.95 and pw < w)

    # ============ px tree (baseline behavior, byte-for-byte) ============
    ddx = 0
    path = "none"
    # nav-band block.
    if y > SH - 130 and est > 0 and pw > est and not standalone \
            and not tall_icon:
        overhang = jdiv(pw - est, 2)
        if overhang <= left_clear:
            d = jdiv(est - pw, 2)
            d = max(d, -x)
            if x + d + pw > x + maxw:
                d = int(maxw - pw)
            ddx = d
            path = "band"
    # (A)-(E) chain
    if path == "none" and est > 0 and not close_row and not tall_icon \
            and not loose and pw > est:
        a = (not standalone and y < 320 and 40 < x < SW * 0.6
             and w > est * 4.5 and h < 74 and not start_locked)
        b = (not start_locked and x <= 60 and w >= SW * 0.83
             and 96 <= h < 120 and w > est * 2.5)
        c1 = header_full and p.get("id") == PAGE_HEADER_ID
        c2 = header_full and y < 340 and p.get("id") != PAGE_HEADER_ID
        d_ = header_full and y > 340 and p.get("id") != PAGE_HEADER_ID
        right_clear = SW - x - w - EDGE_MARGIN
        screen_mid = abs(x + w / 2.0 - SW / 2.0) <= 24
        balanced = (left_clear > 0 and right_clear > 0
                    and min(left_clear, right_clear)
                    >= 0.7 * max(left_clear, right_clear))
        e = (not standalone and w <= est * 1.35 + 2 and pw >= est
             and screen_mid and balanced)
        # (E)'s !wideRow: redundant — wideRow needs w > est*2.5,
        # (E) needs w <= est*1.35+2 (impossible for est>4).
        if a or b or d_:
            ddx = clamp_center(w, pw, x)
            path = ("A" if a else ("B" if b else "D"))
        elif c1 or c2:
            d = max(54, -x)  # (int)(24 * 2.25)
            if x + d + pw > x + maxw:
                d = int(maxw - pw)
            ddx = d
            path = ("C1" if c1 else "C2")
        elif e:
            ddx = clamp_center(w, pw, x)
            path = "E"
    # (F) button block: ddx stays 0 (the inner re-derivation sets width = w
    # -> ddx 0); the outer conditions only matter as an attribution tag.
    if path == "none" and est > 0 and pw > est and not start_locked and x > 30 \
            and SW * 0.28 < w < SW * 0.65 and 96 <= h <= 130 \
            and w > est * 2.0:
        ddx = 0
        path = "F"

    # ============ frame-1 wiring (profile mode only) =====================
    # The profile branch is a FALL-THROUGH centerer at the END of the
    # !multiline ddx block: it claims a pill ONLY when no px gate fired
    # (ddx is still the left default 0), the id is unambiguously
    # center-aligned, and the pill is narrower than the CJK extent.
    # Consequences (verified on the canonical set: every projected mover
    # arrives from path 'none', so no gate-placed pill is re-claimed):
    #   * band/(A)/(B)/(C1)/(C2)/(D)/(E) pills already have ddx set ->
    #     untouched (nav tabs keep the band's icon-center; left-inset
    #     headers keep the 24dp inset until the (C1) release — centering
    #     them would expose the CJK, rule 4, so "known mismatch" items are
    #     NOT frame-1 movers);
    #   * (F) pills hug the node (ddx 0) but are PROFILE_BTN, not
    #     PROFILE_CENTER -> untouched;
    #   * only px-left single-line PROFILE_CENTER pills move (27 on the
    #     canonical set).
    if profile and ddx == 0 and v == "PROFILE_CENTER" and est > 0 \
            and pw > est:
        ddx = clamp_center(w, pw, x)
        path = "profile"
    return ddx, path


def line_class(p, est, fs, shp):
    """Recover the pill's LINE CLASS from the rendered geometry the app
    itself dumps (node dims + shape class + rendered font fsPx). Offline
    stand-in for the runtime `multiline` flag.

    Java height (computeLayout ~818-852):
      single-line: h = (standalone?fs*1.35 : tallIcon?fs*1.4 :
                        loose?fs*1.35 : node_h) + 2*padV,  clamped >= minH
      wrapped:     h = lines*fs*1.25 + 2*padV  (lines 1..8, then maxPillH)
    A 2-line CJK node (node_h ~ 2 lines) with a short single-line translation
    makes the single model (hugs node_h) ~= the 2-line wrap model, so the
    observed height genuinely cannot separate them offline. Rule:
      * argmin over all candidate height models (single + 2..8 line);
      * the two nearest models within 4px of each other -> 'ambig';
      * else the argmin's class wins ('single' / 'multi').
    If fsPx is absent, short single-liners: 'single' (the mirror
    self-test validates their ddx). Returns 'single'|'multi'|'ambig'."""
    node_h = p["node"][3] - p["node"][1]
    if fs <= 0:
        return "single"
    padv = max(2, int(fs * 0.3))
    min_h = max(int(fs) + 2 * padv, 20)
    if shp == "standalone":
        single = int(fs * 1.35) + 2 * padv
    elif shp == "tallIcon":
        single = int(fs * 1.4) + 2 * padv
    elif shp == "loose":
        single = int(fs * 1.35) + 2 * padv
    else:
        single = node_h + 2 * padv
    single = max(single, min_h)
    obs = p["pill"][3]
    models = [(abs(single - obs), "single", single)]
    for L in range(2, 9):
        m = int(L * fs * 1.25) + 2 * padv
        models.append((abs(m - obs), "%dL" % L, m))
    models.sort(key=lambda t: (t[0], t[2]))
    top, runner = models[0], models[1]
    if top[0] <= 4 and runner[0] <= 4 and abs(top[2] - runner[2]) <= 6:
        return "ambig"
    return "single" if top[1] == "single" else "multi"


def audit(baseline_dir, repo):
    profile = json.loads((Path(repo) / "app" / "src" / "main" / "assets"
                          / "view_profiles.json").read_text(encoding="utf-8"))
    base = Path(baseline_dir)
    runs = sorted(d.name for d in base.iterdir()
                  if d.is_dir() and (d / "pills.json").exists())

    total = 0
    moved = 0
    unexplained = 0
    verdict_hist = {}
    gate_pills = {g: 0 for g in GATE_ORDER}
    gate_ids = {g: set() for g in GATE_ORDER}
    movers = []
    mirror_bad = []
    ambig = []

    for run in runs:
        pills = json.loads((base / run / "pills.json").read_text())
        for p in pills:
            total += 1
            x, y = p["node"][0], p["node"][1]
            rel_L = p["pill"][0] - x
            vid = p.get("id") or ""
            v = profile_verdict(flags_of(profile, vid))
            verdict_hist[v] = verdict_hist.get(v, 0) + 1
            node_w = p["node"][2] - p["node"][0]
            node_h = p["node"][3] - p["node"][1]
            est = p.get("est", 0) or 0
            fs = float(p.get("fsPx") or 0)
            close_row, _lc, _mw = sibling_facts(p, pills)
            est_px = estimate_px(node_h)
            st, ti, wd, lo = shape_classes(est, node_w, node_h, est_px, close_row)
            shp = ("standalone" if st else
                   "tallIcon" if ti else
                   "loose" if lo else "normal")

            lc = line_class(p, est, fs, shp)
            if lc == "ambig":
                # Cannot decide single vs wrapped offline. The ONLY case that
                # matters is PROFILE_CENTER (the sole mover-eligible
                # verdict): such a pill MIGHT be a frame-1 mover, so it stays
                # in the ambiguity set for the phone diff to reconcile.
                # Safe direction: it is NOT predicted as a mover here.
                if v == "PROFILE_CENTER":
                    pw = p["pill"][2]
                    can_move = est > 0 and pw > est  # profile width>est guard
                    ambig.append("[{}] {} id={} est={} fs={} node=({},{},{},{}) "
                                 "ph={} pillW={} — single-vs-wrapped unresolved "
                                 "offline; {} phone diff settles it"
                                 .format(run, p.get("key"), vid, est,
                                         round(fs, 1), x, y, node_w, node_h,
                                         p["pill"][3], pw,
                                         "POSSIBLE mover —" if can_move
                                         else "cannot move (width<=est) —"))
                gate_pills["none"] += 1
                if vid:
                    gate_ids["none"].add(vid)
                continue
            if lc == "multi":
                # Out of the horizontal tree (frame 1 does not change wrap):
                # ddx stays 0 in both baseline and frame 1. Verify that.
                if abs(rel_L) > TOL:
                    unexplained += 1
                    mirror_bad.append(
                        "[{}] {} id={} wrap pill with ddx={} (expected 0)"
                        .format(run, p.get("key"), vid, rel_L))
                gate_pills["wrap"] += 1
                if vid:
                    gate_ids["wrap"].add(vid)
                continue

            ddx0, path0 = resolve_ddx(p, pills, v, profile=False)
            if abs(ddx0 - rel_L) > TOL:
                # Mirror self-test failure: the tree does not reproduce the
                # observed baseline. Report loudly — the projection below
                # is only as good as this.
                unexplained += 1
                mirror_bad.append(
                    "[{}] {} id={} node=({},{},{},{}) path={} ddx tree={} "
                    "observed={} (MIRROR MISMATCH)".format(
                        run, p.get("key"), vid, p["node"], path0, ddx0, rel_L))
                gate_pills["none"] += 1
            else:
                gate_pills[path0] += 1
                if vid:
                    gate_ids[path0].add(vid)

            ddx1, path1 = resolve_ddx(p, pills, v, profile=True)
            if abs(ddx1 - rel_L) > TOL:
                moved += 1
                w, h = p["node"][2] - p["node"][0], p["node"][3] - p["node"][1]
                if path1 == "profile" and path0 in ("A", "B", "D", "C1",
                                                    "C2", "E", "band"):
                    # Unreachable under the fall-through design (those pills
                    # leave ddx != 0 and cannot be re-claimed): a pill whose
                    # OBSERVED ddx differs from its own px target is a mirror
                    # bug or a data problem, not a frame-1 move.
                    verdict = ("BUG: the px gate placed this pill ({}), so "
                               "frame-1 must not re-move it — re-examine"
                               ).format(path0)
                elif path1 == "profile" and path0 in ("none",):
                    verdict = ("INTENDED frame-1 move (px left it, profile "
                               "centers; the profile replaces the px guess"
                               )
                elif path1 == "profile":
                    verdict = "moved from {}: document".format(path0 or "?")
                else:
                    verdict = "UNREACHABLE: non-profile path as a mover"
                movers.append("[{}] {} id={} path {} -> {} node=({},{},{},{}) "
                              "dw={} est={} pillW={} ddx {} -> {} ({:+d}) :: {}"
                              .format(run, p.get("key"), vid, path0, path1,
                                      x, y, w, h, p["node"][2] - p["node"][0],
                                      p.get("est", 0), p["pill"][2],
                                      rel_L, ddx1, ddx1 - rel_L, verdict))

    print("== step-4 layout audit (baseline {}) ==".format(baseline_dir))
    print("pills={} | verdicts: {}".format(total, verdict_hist))
    print("baseline attribution (which px place decided the observed ddx):")
    for g in GATE_ORDER:
        if gate_pills[g]:
            print("   {:<14} {:>3} pills  {:>3} ids".format(
                g + ":", gate_pills[g], len(gate_ids[g])))
    if mirror_bad:
        print("   mirror mismatches: {} (the tree does not reproduce the "
              "observed baseline — fix the tree before trusting the "
              "projection)".format(len(mirror_bad)))
        for m in mirror_bad:
            print("     " + m)
    else:
        print("   mirror self-test: ALL single-line pills reproduced "
              "(tree == observed px runtime)")
    if ambig:
        print("   AMBIGUOUS LINE CLASS (offline, must settle on the phone "
              "diff; NOT predicted as movers): {}".format(len(ambig)))
        for m in ambig:
            print("     " + m)

    print()
    print("frame-1 movers: {} (projected; phone diff must list exactly "
          "these{}".format(moved,
          "+ the ambiguous set if any line-class misfired)"))
    for m in movers:
        print("   " + m)

    print()
    print("gate coverage -> frames 2/3/4 (a frame deletes its gate when the")
    print("frame-1 diff is closed; coverage shows whose behavior the gate")
    print("still carries on the canonical set):")
    for g in ("A", "B", "D"):
        ids = gate_ids[g]
        covered = {i for i in ids
                   if profile_verdict(flags_of(profile, i)) == "PROFILE_CENTER"}
        blocking = sorted(i for i in ids if i not in covered)
        print("   gate {} -> frame {}: {} ids | PROFILE_CENTER: {} | "
              "NOT profile-covered: {}".format(
                  g, FRAME_OF[g],
                  sorted(ids) if len(ids) <= 12 else "%d total" % len(ids),
                  len(covered),
                  blocking if blocking else "none (vacuum: the gate places "
                  "nothing here — deletion provable by empty diff)"))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-v"]
    base = args[0] if args else "tools/golden/pre_step4_96_7282"
    audit(base, ".")
