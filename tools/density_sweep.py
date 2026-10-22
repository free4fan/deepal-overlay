#!/usr/bin/env python3
"""Density sweep — the project's density-invariance test (DESIGN.md 10-21).

Goal (the invariant under test):

    the overlay works on ANY phone with ANY resolution iff all positioning
    and sizing logic is dp/sp-agnostic — the SAME physical node must give
    the SAME layout in dp at every density.

Method (no phone, no screenshot — pure computation):

  1. input: one app dump (per-screen `pills.json` — a11y node rect in px +
     RU text + id + `est` + `sp`, the exact computeLayout input; see the
     DESIGN.md "отклонение от ТЗ" note on why pills.json, not a raw
     uiautomator dump);
  2. self-check: the full computeLayout mirror (tools/density_sweep_mir.py)
     must reproduce the app's OWN pill rects at the dump's native density
     (±2px on x/y/w/h). A failing pill is MIRROR-BUG and does NOT enter
     the findings (a port bug would otherwise masquerade as a density
     defect);
  3. sweep: node(est) px' = dp × d', screen px' = (960/2.25)×d' ×
     (2142/2.25)×d' (same physical display expressed at 8 densities
     d ∈ {1.0, 1.5, 2.0, 2.25, 2.75, 3.0, 3.5, 4.0}), mirror rerun at d',
     output back to dp;
  4. compare: |Δ| ≤ 0.5dp on ddx, ddy, width, height, fs (the node-relative
     sides L/T/R/B are ddx/ddy/h+ddy/w+ddx) across densities, and every
     NAMED gate condition (the mirror's `trail`) must keep its boolean —
     a condition flip is a DEFECT even with a small Δ (the silent
     «Автогид» class: the gate stops firing on another density without
     moving the pill on this one).

Known noise axis (reported, not hidden): the INPUT is quantized to integer
px per density (a 40.444dp node is 91px @2.25 but 121px @3.0), so the sp
estimate — and everything derived from it — carries up to ~1px of
synthesis noise at the INPUT, largest in dp at d=1.0 (1px = 1dp). A
px-constant defect shows up as a large Δ or a condition flip at d' > d0 as
well (the node moves, the constant does not) — the report tags d=1.0-only
mild Δ's as quantization candidates.

Run:
  python3 tools/density_sweep.py                        (all 11 screens)
  python3 tools/density_sweep.py <baseline_dir> [screen...]
  --no-word-wrap         (device was captured with word_wrap ON — the
                           default mirrors the device)
  --tol DP               (default 0.5)
  --frame1               (mirror the shipped v97 build on all densities;
                           default: the v96 build that produced the dump —
                           the v96↔v97 diff is proven clean, so the list
                           holds for both)
  --report FILE          (full JSON: verdict, totals, per-node dp/paths/
                           flips/dev; the data behind the text report)

Exit codes: 0 = PASS, 1 = DEFECTS PRESENT (the honest outcome pre-dp-
refactoring — a sweep that ends here has NOT passed), 2 = PARTIAL
(mirror port-defect: findings for those nodes are not yet computable).
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import density_sweep_mir as M  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "s4", Path(__file__).with_name("step4_layout_audit.py"))
s4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s4)  # noqa: E402

BASELINE_DEFAULT = ROOT / "tools/golden/pre_step4_96_7282"
DENSITIES = [1.0, 1.5, 2.0, 2.25, 2.75, 3.0, 3.5, 4.0]
BASE_D = 2.25                 # the baseline device: 960 x 2142
TOL_DP = 0.5
MIRROR_OK = "ok"
MIRROR_BUG = "MIRROR-BUG"


# ------------------------------ inputs ------------------------------------
def load_profile():
    """view_profiles.json → the three inputs computeLayout consumes from it:
    align (the ProfileAlign classifier verdict per id = alignFor), the RAW
    sl set (isStartLocked), and the real font sp per id."""
    prof = json.loads((ROOT / "app/src/main/assets/view_profiles.json")
                      .read_text())
    align, start_locked, font_sp = {}, set(), {}
    for k, v in prof.items():
        if not isinstance(v, list):
            continue
        if len(v) > 0 and v[0] is not None:
            font_sp[k] = int(round(v[0]))
        f = s4.flags_of(prof, k)
        if f.get("sl", 0) == 1:
            start_locked.add(k)
        align[k] = s4.profile_verdict(f)
    return align, start_locked, font_sp


def load_screen(screen_dir):
    pills = json.loads((screen_dir / "pills.json").read_text())
    return [p for p in pills if len(p.get("node", [])) == 4]


def screen_real_h(specs):
    """Proxy for realDisplayHeight (not in the dump): max node bottom at
    the target density. The band threshold real_h−130 must sit BETWEEN the
    nav-tab row (nav-tab x above it... i.e. the nav tabs sit ABOVE the
    threshold) and the lowest content row; max_node_bottom satisfies both
    for all captured screens (nav-band content behind the tab bar is
    excluded by the app; the self-check verifies the band pills)."""
    return max(sp.y + sp.h for sp in specs)


def app_est_sp(h_px, d):
    """estimateTextSize (TranslationService:863), float32 chain:
    clamp(float(h)/float(d) * 2/3f, 10, 24)."""
    v = M.jf(M.jfd(float(h_px), d) * C23)
    return max(10.0, min(v, 24.0))


def scale(pills, d):
    """All dump px → the same physical display at density d, as the app
    itself would DERIVE them on a synthetic device there:
      * node rect  = round(dp × d')   (a11y bounds are integer px);
      * sp estimate = app_est_sp(h', d') (recomputed from the QUANTIZED
        node height, exactly like estimateTextSize does at runtime — the
        small per-density sp jitter the app really has is part of the
        model, not hidden);
      * est        = est × (sp'/sp) (the app's estimateSourceWidth is
        proportional to the clamped sp — w = K · em, em = sp·d)
        rounded to integer px; at d'=d0 this is the dump's est itself."""
    f = d / BASE_D
    out = []
    for p in pills:
        n = p["node"]
        x0, y0, x1, y1 = (round(v * f) for v in n)
        sp0 = p.get("sp", 0.0) or 0.0
        sp1 = app_est_sp(y1 - y0, d)
        est = p.get("est") or 0
        est1 = round(est * (sp1 / sp0) * f) if (est and sp0 > 0) \
            else round(est * f)
        # the device's REAL rendered font for this node (fsPx in the dump,
        # measured at BASE_D) expressed in px at density d: the app sets a
        # FLOAT px font (float sp × d, unrounded — the Java profile path sets
        # realFontSp·density directly), so it grows with density exactly
        # like any sp·d. A missing/zero fsPx keeps the estimate fallback.
        fs0 = p.get("fsPx") or 0
        real_fs = M.jf(fs0 * f) if fs0 else 0.0
        out.append(M.Spec(x0, y0, x1 - x0, y1 - y0,
                          p.get("text", ""), est1,
                          sp1 if est else sp0,
                          p.get("id") or None,
                          real_fs=real_fs))
    return out


# 2f/3f as Java's float constant (single rounding, once)
C23 = 0.6666666839351654


def scale_screen(d):
    return round(960.0 / BASE_D * d), round(2142.0 / BASE_D * d)


# ------------------------------ one run -----------------------------------
def run_screen(specs, ctx_bag, word_wrap, frame1):
    d = ctx_bag.d
    sw, sh = scale_screen(d)
    real_h = screen_real_h(specs)
    ctx = M.Ctx(d, sw, real_h, ctx_bag.align, ctx_bag.start_locked,
                ctx_bag.font_sp)
    runs = {}
    for s in specs:
        trail = []
        out = M.compute_layout(s, word_wrap, specs, ctx, trail,
                               allow_deep=True, frame1=frame1)
        runs[(s.x, s.y)] = (out, trail)
    return runs


def trail_index(trail):
    idx = {}
    for e in trail:
        v = e["value"]
        # log() stores the condition boolean as a 1-tuple in several
        # branches — normalize to the first element
        idx[e["cond"]] = dict(e, value=(v[0] if isinstance(v, (tuple, list))
                                        and v else v))
    return idx


def dp_of(out, d):
    return dict(ddx=out["ddx"] / d, ddy=out["ddy"] / d,
                w=out["width"] / d, h=out["height"] / d,
                fs=out["fs_px"] / d)


# --------------------------- self-check @ D0 -------------------------------
def _dev_class(dev, out, p, pin):
    """why the self-check deviated (documented, keeps the sweep honest).
    pin = 's' (an exact single-line W₁ pin), 'l' (an L-line interval pin),
    or None (the char-class model — the documented approximation):
    model-boundary[-approx] — the line-break / text-width model got the
      render state ~1 line or ~one font step off (a pinned interval is
      still an INTERVAL; a borderline text sits on its edge; the char
      class has no width equation at all). Excluded from the findings,
      listed, not silent;
    port? — otherwise: a real defect of the port for that node."""
    fs = p.get("fsPx") or 0
    dh, dw, dx = dev.get("h", 0), dev.get("w", 0), dev.get("x", 0)
    line = (fs * 1.25) if fs else 30
    padv = M.ic(M.jf(fs * 0.3)) if fs else 2
    padv = max(2, padv)
    lh = M.ic(M.jf(fs * 1.25)) if fs else 24
    pw = p["pill"][2]
    padh = max(4, M.ic(M.jf(fs * 0.4))) if fs else 4
    # the mirror's ddx/ddy tree runs ONLY when !multiline — so a flip in
    # the render state itself (the mirror wrapped where the device stayed
    # on one line, or vice versa — the text model's output) is a
    # STRUCTURAL source of x/y deviation: the whole tree skipped or ran
    # where it should not have. Relax the x bound for exactly that case,
    # still bounded by the width mismatch + one line of centering.
    obs_single = fs > 0 and pw > 0 and \
        p["pill"][3] < 2 * lh + 2 * padv
    ml_flag = bool(out and out.get("multiline"))
    # DIFFERENT render state: one side ran the !multiline ddx/ddy tree,
    # the other skipped it — its output x/y is then not bound by the
    # width mismatch (the tree's ddx is unrelated to text width). Relax
    # the x bound for exactly that case.
    ml_flip = obs_single != ml_flag
    # x is otherwise model-derived ONLY through the centering paths
    # (ddx is a pure function of node_w and width there: Δx = Δwidth/2 at
    # most); every other path fixes ddx from node coords + gates → an x
    # deviation there is port damage, not model noise.
    centering = out["path"] in ("band", "A", "B", "C1", "C2", "D", "E",
                                "profile")
    if centering or ml_flip:
        ok_x = abs(dx) <= abs(dw) / 2 + line + 2
    else:
        ok_x = abs(dx) <= 2
    ok_h = abs(dh) <= line + 2 * padv + 2     # ±1 line of render state
    if pin is None:
        ok_w = True                           # char class: width unconstrained
    elif pin == "s":
        ok_w = abs(dw) <= line + 2
    else:                                      # 'l': the interval spans A px
        ok_w = abs(dw) <= 0.5 * (pw - 2 * padh) + line
    cls = "model-boundary" + ("" if pin else "-approx")
    if not (out and out.get("multiline")):
        return cls if (ok_x and ok_h and ok_w) else "port?"
    # mirror multiline: ±1 line of render state; both widths come from
    # the capped equation (fit_w), so w stays bounded
    return cls if (ok_x and ok_h and abs(dw) <= line + 2 * padv) else "port?"


def self_check(pills, ctx_bag, word_wrap, frame1=False):
    """Mirror vs the APP'S OWN output at the native density.
    Observed: pill[x,y,w,h]; expected: node + (ddx, ddy), width, height.
    Tolerance ±2px. Deviations over tol are CLASSIFIED: model-boundary*
    are the documented text-model limits (those pills are EXCLUDED from
    the findings, but listed, not silent); port? marks a real port
    defect (the mirror would then be what is measured)."""
    _slopes, kinds = build_slopes(pills)
    bag0 = _bag_at(ctx_bag, BASE_D)
    runs = run_screen(scale(pills, BASE_D), bag0, word_wrap, frame1=frame1)
    problems = {}
    for p in pills:
        k = (p["node"][0], p["node"][1])
        obs = p["pill"]
        out, _trail = runs.get(k, (None, None))
        if out is None:
            problems[k] = {"cls": "port?", "dev": "missing run"}
            continue
        ex = [p["node"][0] + out["ddx"], p["node"][1] + out["ddy"],
              out["width"], out["height"]]
        dev = {s: e - o for s, e, o in zip("xywh", ex, obs)}
        if any(abs(v) > 2 for v in dev.values()):
            problems[k] = {"cls": _dev_class(dev, out, p,
                                             kinds.get(p.get("text") or "")),
                           "dev": dev}
    return problems, runs


# ------------------------------ sweep --------------------------------------
class _DenseBag:
    """a screen-context bag bound to one density (d + the profile inputs)"""
    def __init__(self, d, align, start_locked, font_sp):
        self.d = d
        self.align, self.start_locked, self.font_sp = (
            align, start_locked, font_sp)


def _bag_at(base_bag, d):
    return _DenseBag(d, base_bag.align, base_bag.start_locked,
                     base_bag.font_sp)


def build_slopes(pills):
    """Per-text width slope W(text,fs) = slope·fs from the baseline, two
    KINDS of pin (advances on a real font are exactly linear in fs, so a
    single measurement at the device's rendered fsPx pins W at ALL sizes):

    (S)  the width is TEXT-dominated and single-line:
         inner = pill_w − 2·padH(fsPx) is an exact device measurement,
         slope = inner / fsPx.  Requires the plain (non-est-capped) width
         equation to have run with the text area winning (wide/loose cap
         and the est-1.35 node cap re-derivable from the dump fields);
         a tall node uses its reduced fs (w−16 model), also recoverable.
    (L)  the device WRAPPED the text to L ≥ 2 lines at width W (w/h at
         the device fs): by the greedy line model W₁(text) lies in
         ((L−1)·A, L·A]  (A = W − 2·padH); pin the MIDPOINT of that
         interval — for L=2 it restores exactly the wrap decision the
         device made, while any slope inside the interval reproduces the
         same single/multi-line outcome.  Used only when (S) is not
         available for the text and the node gave no width equation at
         all (the width was fully capped).

    Unpinned texts fall back to calibrated char-class units (the
    documented approximation — those pills cannot anchor findings).
    Returns (slopes, kinds): kinds maps text -> 's' | 'l' (the dev
    classifier bounds use the pin kind)."""
    slopes, kinds = {}, {}
    # ---------------- pass 1: exact single-line (S) pins --------------
    for p in pills:
        fs = p.get("fsPx") or 0
        n = p["node"]
        t = p.get("text") or ""
        if not fs or not t or p["pill"][2] <= 0:
            continue
        if t in slopes:
            continue
        pw, ph = p["pill"][2], p["pill"][3]
        padh = max(4, M.ic(M.jf(fs * 0.4)))
        padv = max(2, M.ic(M.jf(fs * 0.3)))
        node_w, node_h = n[2] - n[0], n[3] - n[1]
        est = p.get("est") or 0
        est_px = s4.estimate_px(node_h)
        close, _lc, maxw = s4.sibling_facts(p, pills)
        stand, tall, wide, loose = s4.shape_classes(
            est, node_w, node_h, est_px, close)
        if stand or tall or wide or loose:
            continue                       # est-capped width: no clean W₁
        node_area = min(node_w, maxw - 2 * padh)
        if ph < 2 * M.ic(M.jf(fs * 1.25)) + 2 * padv:
            # one line tall; the plain equation's text area won when it
            # exceeds the (possibly capped) node area — a strict measure
            inner = pw - 2 * padh
            if inner > node_area:
                slopes[t] = inner / fs
                kinds[t] = "s"
            continue                       # node/cap-dominated: no W₁
    # ---------------- pass 2: L-line interval (L) pins ----------------
    # the probes measure the CHAR-CLASS model (the unpinned baseline the
    # self-check compares against): run them with the slope map cleared
    _saved = M._TEXT_SLOPES
    M.set_text_slopes({})
    try:
        for p in pills:
            fs = p.get("fsPx") or 0
            n = p["node"]
            t = p.get("text") or ""
            if not fs or not t or p["pill"][2] <= 0:
                continue
            if t in slopes:
                continue
            pw, ph = p["pill"][2], p["pill"][3]
            padh = max(4, M.ic(M.jf(fs * 0.4)))
            padv = max(2, M.ic(M.jf(fs * 0.3)))
            node_w, node_h = n[2] - n[0], n[3] - n[1]
            est = p.get("est") or 0
            est_px = s4.estimate_px(node_h)
            close, _lc, maxw = s4.sibling_facts(p, pills)
            stand, tall, wide, loose = s4.shape_classes(
                est, node_w, node_h, est_px, close)
            if stand or tall or wide or loose:
                continue                   # est-capped width: no interval
            lh = M.ic(M.jf(fs * 1.25))
            if lh <= 0:
                continue
            lines = min((ph - 2 * padv) // lh + 1, 3)
            if lines >= 2:
                pin = _l_pin(t, pw - 2 * padh, fs, lines)
                if pin is not None:
                    slopes[t] = pin
                    kinds[t] = "l"
    finally:
        M.set_text_slopes(_saved)
    return slopes, kinds


def _l_pin(text, avail, fs, L):
    """Midpoint of the sub-range of the device's W₁ interval
    ((L-1)·A, L·A] where THIS mirror's greedy layout needs exactly L
    lines at `avail` (build_slopes (L)): line count is the observable,
    the interval is its inverse image; None when no slope there does
    (the model can't place L lines in the box at this size — the text
    stays unpinned and is classified as the model limit, not a port)."""
    lo, hi = (L - 1) * avail, L * avail
    n = 40
    step = (hi - lo) / (n - 1)
    idx = [i for i in range(n)
           if M.text_lines(text, lo + i * step, fs)[0] == L]
    if not idx:
        return None
    best_a, best_b = idx[0], idx[0]
    a = b = idx[0]
    for i in idx[1:]:
        if i == b + 1:
            b = i
        else:
            a, b = i, i
        if b - a > best_b - best_a:
            best_a, best_b = a, b
    return ((lo + best_a * step) + (lo + best_b * step)) / 2.0 / fs


def sweep(pills, ctx_bag, word_wrap, tol, frame1=True):
    M.set_text_slopes(build_slopes(pills)[0])
    problems, runs0 = self_check(pills, ctx_bag, word_wrap, frame1=frame1)
    all_runs = {BASE_D: runs0}
    for d in DENSITIES:
        if d == BASE_D:
            continue
        all_runs[d] = run_screen(scale(pills, d), _bag_at(ctx_bag, d),
                                 word_wrap, frame1)

    def scaled_k(p, d):
        return (round(p["node"][0] * d / BASE_D),
                round(p["node"][1] * d / BASE_D))

    report = []
    for p in pills:
        k0 = (p["node"][0], p["node"][1])
        prob = problems.get(k0)
        rec = {
            "id": p.get("id") or "",
            "text": p.get("text", ""),
            "node_px": p["node"],
            "mirror": MIRROR_BUG if prob else MIRROR_OK,
            "mirror_cls": prob["cls"] if prob else None,
            "mirror_dev": prob["dev"] if prob else None,
            "dp": {}, "paths": {}, "flips": [],
            "max_d": 0.0, "worst": None,
        }
        base_dp = dp_of(all_runs[BASE_D][k0][0], BASE_D)
        rec["dp"][str(BASE_D)] = base_dp
        rec["paths"][str(BASE_D)] = all_runs[BASE_D][k0][0]["path"]
        t0 = trail_index(all_runs[BASE_D][k0][1])
        # the quantization-noise allowance: the synthetic device integers
        # (node rounding 0.5px, the sp recompute jitter, est rounding,
        # pad int truncation) propagate to at most ~3px of output even on
        # a perfectly dp-clean layout. A real px-constant defect shows as
        # a large Δ AND/OR a named-condition flip below; anything inside
        # this allowance without a flip is noise, not code.
        def tol_noise(dxx):
            return 0.5 + 3.0 / dxx

        for d in DENSITIES:
            if d == BASE_D:
                continue
            k = scaled_k(p, d)
            out, trail = all_runs[d][k]
            v = dp_of(out, d)
            rec["dp"][str(d)] = v
            rec["paths"][str(d)] = out["path"]
            for side in ("ddx", "ddy", "w", "h", "fs"):
                delta = abs(v[side] - base_dp[side])
                if delta > rec["max_d"]:
                    rec["max_d"] = delta
                    rec["worst"] = (d, side, delta)
            t1 = trail_index(trail)
            for cond, e0 in t0.items():
                e1 = t1.get(cond)
                if e1 is not None and bool(e0["value"]) != bool(e1["value"]):
                    rec["flips"].append([d, cond,
                                         bool(e0["value"]),
                                         bool(e1["value"])])
        # approx-model pills (the device font's variance moves the wrap /
        # width model ~1 line or ~few px off) cannot anchor findings
        # honestly: reported, but excluded from the defect list; a port?
        # pill means the MIRROR is being measured, not the code — then the
        # screen verdict is "mirror needs fixing", not "code is clean/defective".
        excluded = prob is not None and prob["cls"].startswith(
            "model-boundary")
        rec["port_defect"] = bool(prob) and not prob["cls"].startswith(
            "model-boundary")
        # DEFECT = a named px condition flipped (the silent gate class)
        # OR a Δ beyond the spec tolerance (0.5dp) once the quantization
        # allowance is subtracted (the synthetic-device input chain: node
        # rounding 0.5px, sp recompute jitter, est rounding, int pads →
        # up to ~3px of output even for a perfectly dp-clean layout).
        wd = rec["worst"][0] if rec["worst"] else BASE_D
        rec["over_spec"] = rec["max_d"] > tol
        rec["noise"] = (rec["over_spec"] and not rec["flips"]
                        and rec["max_d"] <= 0.5 + 3.0 / wd)
        rec["fails"] = (not excluded) and (
            bool(rec["flips"]) or (rec["over_spec"] and not rec["noise"]))
        report.append(rec)
    return report, problems


# ------------------------------ report -------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_dir", nargs="?", default=str(BASELINE_DEFAULT),
                    help=argparse.SUPPRESS)
    ap.add_argument("screens", nargs="*",
                    help="screen names (positional: the baseline dir "
                         "MUST be given first: "
                         "`python3 tools/density_sweep.py <dir> [screen…]`)")
    ap.add_argument("--word-wrap", action="store_true", default=False,
                    help="force word_wrap ON (a user setting of the app). "
                         "Default OFF = the state of the baseline "
                         "capture: proved by the dump — gate (F)'s "
                         "button-hug (Java 1079-1119, pill == the exact "
                         "368x102 button node) is reachable ONLY in the "
                         "!multiline branch, and the baseline has it "
                         "(«Конечно», dialog_keyless). Two-line pills in "
                         "the dump come from the app's INTERNAL wrap "
                         "loop (it runs under !multiline too), not from "
                         "the user flag.")
    ap.add_argument("--tol", type=float, default=TOL_DP)
    ap.add_argument("--frame1", action="store_true", default=False,
                    help="mirror the SHIPPED v2.10.45 build (frame-1 "
                         "profile fall-through) on all densities. "
                         "Default (the self-check build the baseline "
                         "dump came from): frame1=False everywhere — "
                         "the v96↔v97 diff is proven clean (6 ddx-only "
                         "moves, tools/_diff_v96_v97.py), so the defect "
                         "list computed here is valid for the shipped "
                         "build as well.")
    ap.add_argument("--report", default=None, help="also write JSON report")
    args = ap.parse_args()

    base_dir = Path(args.baseline_dir)
    if not base_dir.is_absolute():
        base_dir = ROOT / base_dir
    if args.screens:
        screens = list(args.screens)
    else:
        screens = sorted(d.name for d in base_dir.iterdir() if d.is_dir())
    word_wrap = args.word_wrap

    class CtxBag:
        d = BASE_D
    ctx_bag = CtxBag()
    ctx_bag.align, ctx_bag.start_locked, ctx_bag.font_sp = load_profile()

    n_ok = n_fail = n_mirror_bug = 0
    kept = {}
    print("density sweep   baseline=%s   word_wrap=%s   tol=%.2fdp"
          % (base_dir.name, word_wrap, args.tol))
    print("densities: %s" % " ".join("%.2f" % d for d in DENSITIES))
    print()
    for screen in screens:
        pdir = base_dir / screen
        if not (pdir / "pills.json").exists():
            print("== %-22s NO pills.json — skipped" % screen)
            continue
        pills = load_screen(pdir)
        rep, problems = sweep(pills, ctx_bag, word_wrap, args.tol,
                              frame1=args.frame1)
        fails = [r for r in rep if r["fails"]]
        mb = [r for r in rep if r["mirror"] == MIRROR_BUG]
        approx = [r for r in mb if r["mirror_cls"].startswith(
            "model-boundary")]
        port = [r for r in mb if r not in approx]
        clean = len(rep) - len(fails) - len(mb)
        n_ok, n_fail, n_mirror_bug = \
            n_ok + clean, n_fail + len(fails), n_mirror_bug + len(mb)
        kept[screen] = rep
        port_s = ""
        if port:
            port_s = "  >>> %d MIRROR PORT-DEFECT: mirror must be fixed " \
                     "before findings are trusted" % len(port)
        print("== %-22s %3d nodes: %2d clean, %2d FAIL, %2d mirror"
              " (approx %d / port? %d)%s"
              % (screen, len(rep), clean, len(fails), len(mb),
                 len(approx), len(port), port_s))
        for r in approx:
            print("   approx%-12s %-16s dev=%s text=%r"
                  % (r["mirror_cls"], (r["id"] or "?")[:16],
                     r["mirror_dev"], r["text"][:20]))
        for r in port:
            print("   MIRROR-PORT? %-16s dev=%s text=%r"
                  % ((r["id"] or "?")[:16], r["mirror_dev"],
                     r["text"][:20]))
        for r in fails:
            d, side, delta = r["worst"]
            p0 = r["paths"]["2.25"]
            pdiffs = {dd: pp for dd, pp in r["paths"].items() if pp != p0}
            p_s = "   path %s->%s" % (p0, dict(list(pdiffs.items())[:3])) \
                if pdiffs else ""
            kind = "FLIP-DEFECT" if r["flips"] else "DX-DEFECT"
            print("   FAIL   %-22s \u0394=%5.2fdp %-3s @%.2f  [%s]%s"
                  % ((r["id"] or "?")[:22], delta, side, d, kind, p_s))
            print("          text=%r node=%s" % (r["text"][:36], r["node_px"]))
            for fd, cond, va, vb in r["flips"]:
                print("        flip %-8s @%.2f  %s -> %s"
                      % (cond, fd, va, vb))
        noisy = [r for r in rep if r["noise"] and not r["fails"]]
        if noisy:
            print("   (noise-only over-spec: %d — Δ inside the 0.5+3px/d "
                  "quantization allowance, no flip)" % len(noisy))
        print()

    n_port = sum(1 for rep in kept.values()
                 for r in rep if r["port_defect"])
    n_flip = sum(1 for rep in kept.values() for r in rep
                 if r["fails"] and r["flips"])
    n_dx = sum(1 for rep in kept.values() for r in rep if r["fails"]
               and not r["flips"])
    n_unv = n_mirror_bug
    verified = n_ok + n_fail
    print("TOTAL: %d nodes — VERIFIED %d (%d clean, %d defect: %d flip, "
          "%d dx) + UNVERIFIED %d (mirror approx / port-?)"
          % (verified + n_unv, verified, n_ok, n_fail, n_flip, n_dx,
             n_unv))
    if n_port:
        print("VERDICT: PARTIAL — findings stand for the %d verified "
              "nodes; %d node(s) are mirror-limited (port-?): the MIRROR "
              "must be fixed for them before their findings count "
              "(exit=%d, CI gate)" % (verified, n_port, 2))
        verdict, exit_code = "PARTIAL", 2
    else:
        if n_fail == 0 and n_mirror_bug == 0:
            print("VERDICT: PASS — no density-defect over tol")
            verdict, exit_code = "PASS", 0
        else:
            print("VERDICT: DEFECTS PRESENT — %d verified nodes, the list "
                  "above is the DP-refactory backlog; 'approx' rows are "
                  "the documented text-model limits (excluded from the "
                  "count). A density sweep that ends here has NOT "
                  "passed: the code below is px-dependent until the "
                  "backlog is refactored (exit=%d, CI gate)"
                  % (verified, 1))
            verdict, exit_code = "DEFECTS", 1

    if args.report:
        rp = Path(args.report)
        if not rp.is_absolute():
            rp = ROOT / rp
        rp.write_text(json.dumps(
            {"baseline": base_dir.name, "word_wrap": word_wrap,
             "tol_dp": args.tol, "frame1": bool(args.frame1),
             "densities": DENSITIES,
             "base_density": BASE_D, "verdict": verdict,
             "totals": {"nodes": verified + n_unv, "verified": verified,
                        "clean": n_ok, "defects": n_fail,
                        "flip_defects": n_flip, "dx_defects": n_dx,
                        "mirror": n_unv, "port_defects": n_port,
                        "noise_only": sum(1 for rep in kept.values()
                                          for r in rep if r["noise"]
                                          and not r["fails"])},
             "screens": {s: rep for s, rep in kept.items()}},
            ensure_ascii=False, indent=1, default=str))
        print("report: %s" % rp)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
