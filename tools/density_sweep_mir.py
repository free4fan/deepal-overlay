#!/usr/bin/env python3
"""Density sweep — mirror of InlineOverlayManager.computeLayout (full path).

Port discipline:
  * Java int ops: jdiv() (truncation toward zero), ic() for (int) casts;
  * Java float ops: jf()/jfd() — the Java code runs in float32 (literals like
    0.6f/1.35f are float32, and int*float promotes to float32). Python float
    is float64: keeping float64 would systematically land on the wrong side
    of a 1px boundary for some node/density combinations, so every Java
    float32 operation is reproduced with a single rounding to IEEE-754 single
    (struct pack/unpack). This is what makes a boundary FLIP in the sweep a
    defect of the Java constant, not an artifact of the port;
  * branch order and every condition are 1:1 with the Java (band block,
    (A)-(F) with (C1)/(C2)/(D) header split, (E), shape classes, width/
    height model, font fit/wrap/preview loops, frame-1 profile fall-through,
    wrapped-1-line ddy fix, row vertical guard with deep pass). The whole
    horizontal ddx block and the single-line ddy live inside `if (!multiline)`
    exactly as in Java;
  * the only modelled element is measureText: advance widths are exactly
    linear in the font size on real fonts (no advance hinting), so
    width(ts) = ts · units(text) is faithful to the MULTIPLICATIVE behavior;
    the character-class coefficients are calibrated against the app's OWN
    output by the self-check at the native density;
  * `start_locked` follows the RAW sl flag set (Java isStartLocked), not the
    classifier verdicts; frame-1 uses the classifier (alignFor) — the sets
    only differ on sl+g ids (0 exist, audited).

`trail` records the boolean value + a margin for every named px condition at
every TOP-LEVEL call, so a flip between densities is attributed to the exact
term. Deep (recursion-stop) passes pass trail=None.
"""

import math
import struct

JMAX = 1 << 30  # stand-in for Integer.MAX_VALUE (only inside a +2f compare)

def jf(x):
    """Round to IEEE-754 single precision (Java float arithmetic)."""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def jfd(a, b):
    """Java float division: exact quotient rounded to float32."""
    return jf(a / b) if b != 0 else 0.0



# T-35 #0: the measurement foundation lives in dp — the app's old 225dpi px
# constants divided by 2.25. float32 dp values + Java's Math.round rule
# (rpx) => byte-exact at d=2.25, physically the same length everywhere.
# Mirrors InlineOverlayManager's *_DP constants 1:1.
EDGE_MARGIN_DP = jf(3.5556)
MIN_LINE_H_DP = jf(8.8889)
NEAR_ROW_DP = jf(21.3333)
ROW_GAP_DP  = jf(2.6667)
NEIGHBOR_MAX_DP = jf(266.6667)
SAME_ROW_DY_DP = jf(22.2222)
PADH_FLOOR_DP = jf(4.0 / 2.25)   # Java: 4 / 2.25f
PADV_FLOOR_DP = jf(2.0 / 2.25)
MIN_PILL_DP = jf(32.0)


def rp(dp, d):
    """dp->px with the app's Math.round rule: float32 product, floor(x+0.5)."""
    return math.floor(jf(jf(dp) * d) + 0.5)

def jdiv(a, b):
    """Java int division: truncation toward zero (Python // floors)."""
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def ic(x):
    """Java (int) cast: truncation toward zero."""
    return int(x)


# ------------------------------ text model ================================
# Advances scale EXACTLY linearly with the font size on real fonts (no
# advance hinting). PRIMARY: the observed per-text slope from the baseline
# itself — for a pill whose width is text-dominated, W(text, fs0) =
# pill_w − 2·padH(fs0) is an exact device measurement, and W at any other
# size is that slope times the size (the device font, not our guess).
# FALLBACK (texts no equation pins down): calibrated char-class units —
# multiplicative, so it cannot fake density-invariance either.
#
# The line-break model is EXACT TextView static layout, not a word
# heuristic: line breaks land AFTER a space (the space is on the left —
# Java's wrapLineCount charges it with the next word: need = space+word)
# and AFTER a hyphen (UAX#14; the word is pre-split, "Ili-Kazakh" →
# ["Ili-", "Kazakh"]). A segment wider than the available width is
# infeasible for the size (Android draws it overflowing on its own line;
# the budget paths count that as no-wrap).
#
# The WRAP_CONTENT height (wordWrap && wrapLines == 0) is the number of
# lines TextView NEEDS for the full text inside (width − 2·padH) — the
# sweep sizes it with the same exact layout (tools/density_sweep.py).
_TEXT_SLOPES = None
_LINE_FACTOR = 1.25        # lh = (int)(fs·1.25) — Java convention; the dump
                           # confirms 2 lines at fs 30.67px → h 94 = 2·ic(1.25fs)+2padV


def set_text_slopes(m):
    global _TEXT_SLOPES
    _TEXT_SLOPES = m or {}


def _units(ch):
    o = ord(ch)
    if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
            or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF):
        return 1.00        # CJK ≈ 1em
    if ch == ' ':
        return 0.30
    if ch == '…':
        return 0.50
    if ch.isalpha():
        return 0.50        # Cyrillic/Latin average (tools/_calib_text_model.py)
    if ch.isdigit():
        return 0.57
    return 0.44            # punctuation


def _prefix(text, fs):
    """prefix-width table (0, w1, w1+w2, …) for `text` at `fs` — the width
    function every line-break query needs. For a SLOPE-pinned text the
    prefix is linear in the char index (the pin fixes the TOTAL; segment
    widths are proportional — the documented assumption)."""
    if _TEXT_SLOPES and text in _TEXT_SLOPES and len(text) > 0:
        per_char = _TEXT_SLOPES[text] * fs / len(text)
        return lambda i: per_char * i
    ps = [0.0]
    for c in text:
        ps.append(ps[-1] + fs * _units(c))
    return lambda i: ps[i]


def measure(text, fs):
    """whole-text advance — slope when pinned, else char classes"""
    return _prefix(text, fs)(len(text))


def _hyphen_splits(text):
    """the Java word list's hyphen pre-split as (start, end) segments of
    space-separated pieces: "Ili-Kazakh" → [(0,4),(4,11)]."""
    segs = []
    pos = 0
    for part in text.split(" "):
        if len(part) > 1 and '-' in part:
            h = 0
            fromidx = 0
            while True:
                h = part.find('-', fromidx)
                if h < 0:
                    break
                segs.append((pos + fromidx, pos + h + 1))
                fromidx = h + 1
            if fromidx < len(part):
                segs.append((pos + fromidx, pos + len(part)))
        else:
            segs.append((pos, pos + len(part)))
        pos += len(part) + 1
    return segs


def text_lines(text, avail, fs):
    """(lines, feasible): the lines TextView's static layout NEEDS for
    `text` at `fs` inside `avail` px. Greedy; breaks after spaces and
    hyphens; a segment wider than `avail` → (0, False)."""
    if avail <= 0:
        return 0, False
    pref = _prefix(text, fs)
    space_adv = fs * _units(' ')
    lines = 1
    x = 0.0
    for s, e in _hyphen_splits(text):
        w = pref(e) - pref(s)
        if w > avail:
            return 0, False
        cost = w + (space_adv if x > 0 else 0.0)
        if x + cost > avail:
            lines += 1
            x = w
        else:
            x += cost
    return lines, True


def _budget_wrap(text, box_w, fs, max_lines, max_hpx, d):
    """Java wrapLineCount, budgeted: 0 when infeasible for the max_lines
    budget or the height cap."""
    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(fs * 0.4)))
    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(fs * 0.3)))
    avail = jf(jf(box_w) - 2.0 * padh)
    if avail < fs:
        return 0
    lines, ok2 = text_lines_capped(text, avail, fs, max_lines)
    if not ok2:
        return 0
    h = jf(jf(lines * fs) * 1.25 + 2.0 * padv)
    if max_hpx < JMAX and h > jf(float(max_hpx) + 2.0):
        return 0
    return lines


def text_lines_capped(text, avail, fs, max_lines):
    """as text_lines but stops at max_lines lines (an overflow → infeasible;
    Java's budget paths use it with the line-budget max)."""
    if avail <= 0:
        return 0, False
    pref = _prefix(text, fs)
    space_adv = fs * _units(' ')
    lines = 1
    x = 0.0
    for s, e in _hyphen_splits(text):
        w = pref(e) - pref(s)
        if w > avail:
            return 0, False
        cost = w + (space_adv if x > 0 else 0.0)
        if x + cost > avail:
            lines += 1
            if lines > max_lines:
                return 0, False
            x = w
        else:
            x += cost
    return lines, True
# ------------------------------ spec / context ============================
class Spec:
    __slots__ = ("x", "y", "w", "h", "text", "est", "sp", "vid", "real_fs")

    def __init__(self, x, y, w, h, text, est, sp, vid, real_fs=0.0):
        (self.x, self.y, self.w, self.h) = (x, y, w, h)
        (self.text, self.est, self.sp, self.vid) = (text, est, sp, vid)
        # the DEVICE-RENDERED text font in px for this node (the dump's
        # fsPx), scaled to the current density like any sp·d value — the
        # app's real font size (TranslationService) is float px, unclamped
        # (the dump shows 20.25px = a 9sp real font). 0 = unknown → the
        # estimate-sp fallback below (the Java pre-profile behavior).
        self.real_fs = real_fs

    @property
    def key(self):
        return "%d,%d" % (self.x, self.y)


class Ctx:
    def __init__(self, density, screen_w, real_h, align, start_locked,
                 real_font_sp):
        self.d = density
        self.sw = screen_w
        self.real_h = real_h
        self.align = align                 # id -> classifier verdict (str)
        self.start_locked = start_locked   # set of ids (raw sl flag)
        self.real_font_sp = real_font_sp   # id -> sp (int, profile)


PAGE_HEADER_ID = "tvTopTitle"


def compute_layout(s, word_wrap, siblings, ctx, trail=None, allow_deep=True,
                   frame1=True):
    """frame1=False port the v2.10.44 (pre-frame-1) build — needed for the
    mirror self-check against the pre_step4_96 baseline (that build has no
    profile fall-through branch). frame1=True is the shipped v2.10.45+."""
    d = ctx.d
    sw = ctx.sw
    x = s.x
    rec = trail is not None and allow_deep

    def log(name, value, margin, detail=""):
        if rec:
            trail.append({"key": s.key, "cond": name, "value": value,
                          "margin": margin, "detail": detail})

    # ---------------- column limit / siblings ----------------------------
    edge_px = rp(EDGE_MARGIN_DP, d)                # SCREEN_EDGE_MARGIN dp
    near_thr = rp(NEAR_ROW_DP, d)                  # NEAR_ROW_THRESHOLD dp
    maxw = max(near_thr, sw - x - edge_px)
    nb_px = rp(NEIGHBOR_MAX_DP, d)                 # ROW_NEIGHBOR_MAX dp
    same_row_dy = rp(SAME_ROW_DY_DP, d)            # ROW_SAME_ROW_MAX_DY dp
    row_gap_px = rp(ROW_GAP_DP, d)                 # ROW_GAP dp
    close_row = False
    gap_below = -1
    left_clear = x
    near = -1
    if siblings is not None:
        for t in siblings:
            if t is s:
                continue
            dx = t.x - x
            same_row = abs(t.y - s.y) <= same_row_dy
            if 0 < dx < nb_px and same_row:
                close_row = True
                if near < 0 or dx < near:
                    near = dx
            elif -nb_px < dx < 0 and same_row:
                left_clear = max(0, min(left_clear, x - (t.x + t.w)))
            dyb = t.y - s.y
            if 0 < dyb < nb_px and t.x < x + maxw and t.x + t.w > x:
                g = t.y - (s.y + s.h)
                if gap_below < 0 or g < gap_below:
                    gap_below = g
        if near > near_thr:
            maxw = min(maxw, near - row_gap_px)
    if gap_below >= 0:
        max_pill_h = s.h + ic(jf(max(0, gap_below) * 0.75))
    else:
        max_pill_h = JMAX

    # ---------------- font (sp domain, density-safe) ----------------------
    # estimatePx = spec.textSizeSp (a float32 clamp(10..24) of h/d*2/3)
    # times density, clamped again (a no-op when the sp is already clamped).
    estimate_sp = min(24.0, max(10.0, s.sp)) if s.sp > 0 else 0.0
    estimate_px = jf(estimate_sp * d)
    estimate_px = max(jf(10.0 * d), min(estimate_px, jf(24.0 * d)))
    # The device font: the REAL font of the node (dp-agnostic sp → px at
    # any density), the profile sp when the node is profile-driven, else
    # the estimate (the Java pre-profile code path — the sp IS the
    # estimate there). Unclamped: the app sets real float px sizes
    # (e.g. 20.25px @2.25 = an unrounded 9sp).
    if s.real_fs and s.real_fs > 0:
        text_px = jf(s.real_fs)
    else:
        font_sp = ctx.real_font_sp.get(s.vid, s.sp) if s.vid else s.sp
        text_px = max(jf(10.0 * d),
                      min(jf(float(font_sp) * d), jf(24.0 * d)))
    base_px = text_px

    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
    est = s.est

    # ---------------- shape classes ----------------------------------------
    stand = (not close_row and est > 0
             and s.w > jf(est * 2.5) and s.h > jf(estimate_px * 1.8))
    tall = (not close_row and not stand and est > 0
            and s.w <= jf(est * 1.35) + 2
            and s.h > jf(estimate_px * 1.6) and s.h < jf(estimate_px * 6.0))
    wide = (not close_row and not stand and not tall
            and est > 0 and s.w > jf(est * 2.5))
    loose = (not close_row and not stand and not tall and not wide
             and est > 0 and s.w > jf(est * 1.7)
             and s.h > jf(estimate_px * 1.8))
    log("shape", (stand, tall, wide, loose), 0,
        "w=%d h=%d est=%d estPx=%.4f closeRow=%s"
        % (s.w, s.h, est, estimate_px, close_row))

    # ---------------- width budget / font fitting --------------------------
    text_cap = 0
    fit_w = maxw
    if loose:
        fit_w = min(fit_w, ic(jf(est * 1.35)) + padh * 2)
    heading_floor_px = jf(16.0 * d)               # (WRAP_DESIRED_SP+4)sp
    heading_cap = False
    if stand:
        text_cap = ic(jf(est * 1.4)) + padh * 2
        fit_w = min(maxw, text_cap)
        at_heading = math.ceil(measure(s.text, heading_floor_px)
                               + jf(heading_floor_px * 0.8))
        if at_heading > text_cap and at_heading <= maxw:
            text_cap = at_heading
            fit_w = at_heading
            heading_cap = True
    if tall and est > 0:
        fs_tib = jfd(jf(base_px * (s.w - 16.0)), est)
        if fs_tib < text_px and fs_tib >= jf(9.0 * d):
            text_px = fs_tib
            padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
            padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))

    text_w = measure(s.text, text_px)

    multiline = word_wrap and (text_w + padh * 2 > fit_w)
    wrap_lines = 0
    preview = None
    if not multiline and text_w + padh * 2 > fit_w:
        t = jfd(text_w, text_px)
        fs1 = jfd(fit_w, jf(t + 0.8))
        if fs1 < jf(12.0 * d):                    # WRAP_DESIRED_SP px
            shown = jfd(s.h, estimate_px) if estimate_px > 0 else 0.0
            implied = jfd(est, s.w) if est > s.w else 1.0
            complete = (est > 0 and estimate_px > 0 and shown >= 2.5
                        and implied >= 2.5 and shown >= jf(implied - 0.6))
            single_node = (est > 0 and estimate_px > 0
                           and s.h <= jf(1.9 * estimate_px))
            wrap_w = min(fit_w, s.w) if (tall and complete) else fit_w
            fs = text_px
            wl = 0
            while fs >= jf(9.0 * d):              # WRAP_FLOOR_SP px
                wl = _budget_wrap(s.text, wrap_w, fs,
                                  8 if complete else
                                  (min(2, line_budget(max_pill_h, fs, d))
                                   if single_node
                                   else line_budget(max_pill_h, fs, d)),
                                  max_pill_h, d)
                if wl != 0:
                    break
                fs = jf(fs - 1.0)
            wrap_lines = wl
            if wrap_lines > 0:
                text_px = fs
                padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
                padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
                text_w = measure(s.text, text_px)
                multiline = True
            elif fs1 >= jf(9.0 * d):
                text_px = fs1
                padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
                padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
                if stand and not heading_cap:
                    text_cap = ic(jf(est * 1.4)) + padh * 2
                text_w = measure(s.text, text_px)
            else:
                pfs = text_px
                pl = 0
                while pfs >= jf(9.0 * d) and preview is None:
                    preview, pl = truncate_to_lines(s.text, fit_w, pfs,
                                                    min(3, line_budget(max_pill_h, pfs, d)),
                                                    max_pill_h, d)
                    if preview is None:
                        pfs = jf(pfs - 1.0)
                if preview is not None:
                    text_px = pfs
                    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
                    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
                    text_w = measure(preview, text_px)
                    multiline = True
                    wrap_lines = pl
                else:
                    scale = jfd(fit_w - padh * 2, text_w) if text_w > 0 else 1.0
                    text_px = max(jf(9.0 * d), jf(text_px * scale))
                    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
                    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
                    if stand and not heading_cap:
                        text_cap = ic(jf(est * 1.4)) + padh * 2
                    text_w = measure(s.text, text_px)
        else:
            text_px = fs1
            padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
            padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
            if stand and not heading_cap:
                text_cap = ic(jf(est * 1.4)) + padh * 2
            text_w = measure(s.text, text_px)

    if not multiline and text_w > jf(fit_w - padh * 2.0) and fit_w >= near_thr:
        clamped = (jfd(jf(text_px * jf(fit_w - padh * 2.0 - 1.0)), text_w)
                   if text_w > 0 else text_px)
        if clamped >= jf(9.0 * d):
            text_px = clamped
            padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
            padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
            text_w = measure(s.text, text_px)
    log("fontFit", (multiline, wrap_lines, ic(text_px)), 0,
        "fitW=%d textW=%.2f preview=%s" % (fit_w, text_w, preview is not None))

    # ---------------- pill width ------------------------------------------
    if multiline:
        width = ic(min(fit_w, s.w)) if (tall and preview is None) else fit_w
    elif tall:
        width = min(maxw, max(s.w, ic(jf(text_w + padh * 2.0))))
    else:
        text_area = min(ic(text_w), maxw - padh * 2)
        node_area = min(ic(s.w), maxw - padh * 2)
        if stand:
            text_area = min(text_area, text_cap - padh)
            node_area = min(node_area, text_cap - padh)
        elif wide:
            node_area = min(node_area, ic(jf(est * 2.2)))
        elif loose:
            node_area = min(node_area, ic(jf(est * 1.35)) + padh)
        width = max(node_area, text_area) + padh * 2

    # ---------------- pill height -----------------------------------------
    if multiline:
        lh = ic(jf(text_px * 1.25))
        if word_wrap and wrap_lines == 0:
            # Java hands the height to WRAP_CONTENT: the TextView lays the
            # FULL text in (width - 2*padH) — resolved here with the exact
            # line layout (the TextView line-break model, ported 1:1).
            need, _feas = text_lines(s.text, max(0, width - padh * 2),
                                     text_px)
            lines = need if need > 0 else 1
        else:
            lines = wrap_lines if wrap_lines > 0 else 2
        height = lines * lh + padv * 2
        if tall or s.h > jf(estimate_px * 2.2):
            height = max(height, s.h)
        height = min(height, max_pill_h)
    else:
        min_h = max(ic(jf(text_px) + padv * 2), rp(MIN_LINE_H_DP, d))  # MIN_SINGLE_LINE_HEIGHT_DP
        if stand:
            h = ic(jf(text_px * 1.35)) + padv * 2
        elif tall:
            h = ic(jf(text_px * 1.4)) + padv * 2
        elif loose:
            h = ic(jf(text_px * 1.35)) + padv * 2
        else:
            h = s.h + padv * 2
        height = max(h, min_h)
        height = min(height, max_pill_h)

    # ---------------- horizontal: band, (A)-(F), frame-1 -------------------
    # Java: int ddx = 0, ddy = 0; if (!multiline) { ddy = (h-height)/2; … }
    ddx = 0
    ddy = 0
    path = "none"
    if not multiline:
        ddy = jdiv(s.h - height, 2)
        y0 = s.y

        band_pred = (y0 > ctx.real_h - 130)        # 130px px-constant
        if band_pred and est > 0 and width > est and not stand and not tall:
            overhang = jdiv(width - est, 2)
            if overhang <= left_clear:
                ddx = jdiv(est - width, 2)
                ddx = max(ddx, -x)
                if x + ddx + width > x + maxw:
                    ddx = ic(maxw - width)
                path = "band"
            log("band", (path == "band",),
                130 - (ctx.real_h - y0) if band_pred else (y0 - (ctx.real_h - 130)),
                "y0=%d thr=%d overhang=%d lc=%d"
                % (y0, ctx.real_h - 130,
                   jdiv(width - est, 2), left_clear))
        else:
            log("band", (False,), (ctx.real_h - 130) - y0,
                "y0=%d thr=%d" % (y0, ctx.real_h - 130))

        start_locked = bool(s.vid and s.vid in ctx.start_locked)
        header_full = (stand and x <= 30 and s.w >= jf(sw * 0.95)
                       and width < s.w)
        page_header = (s.vid == PAGE_HEADER_ID)

        if (path == "none" and est > 0 and not close_row and not tall
                and not loose and width > est):
            a_g = (not stand and y0 < 320 and 40 < x < jf(sw * 0.6)
                   and s.w > jf(est * 4.5) and s.h < 74
                   and not start_locked)
            b_g = (not start_locked and x <= 60 and s.w >= jf(sw * 0.83)
                   and 96 <= s.h < 120 and s.w > jf(est * 2.5))
            c1 = header_full and page_header
            c2 = header_full and (not page_header) and y0 < 340
            d_g = header_full and (not page_header) and y0 > 340
            right_clear = sw - x - s.w - 8
            screen_mid = abs(x + s.w / 2.0 - sw / 2.0) <= 24
            balanced = (left_clear > 0 and right_clear > 0
                        and min(left_clear, right_clear)
                        >= jf(0.7 * max(left_clear, right_clear)))
            e_g = (not stand and not wide and s.w <= jf(est * 1.35) + 2
                   and width >= est and screen_mid and balanced)
            log("gateA", (a_g,), 320 - y0 if y0 < 320 else y0 - 320,
                "y0=%d x=%d w=%d h=%d est=%d stand=%s sl=%s 40<x<0.6sw=%s "
                "w>4.5est=%s h<74=%d"
                % (y0, x, s.w, s.h, est, stand, start_locked,
                   40 < x < jf(sw * 0.6), s.w > jf(est * 4.5), s.h < 74))
            log("gateB", (b_g,),
                (96 - s.h) if s.h < 96 else (s.h - 120) if s.h >= 120 else 0,
                "h=%d x=%d w=%d 0.83sw=%.1f est=%d sl=%s"
                % (s.h, x, s.w, jf(sw * 0.83), est, start_locked))
            log("gateHC", (c1, c2), 340 - y0 if y0 < 340 else y0 - 340,
                "headerFull=%s y0=%d id=%s" % (header_full, y0, s.vid))
            log("gateD", (d_g,), 340 - y0 if y0 < 340 else y0 - 340,
                "headerFull=%s y0=%d id=%s" % (header_full, y0, s.vid))
            log("gateE", (e_g,), 0,
                "mid=%s bal=%s w<=1.35est+2=%s lc=%d rc=%d"
                % (screen_mid, balanced, s.w <= jf(est * 1.35) + 2,
                   left_clear, right_clear))
            if a_g or b_g or d_g:
                ddx = _cl_center(s.w, width, x, maxw)
                path = "A" if a_g else ("B" if b_g else "D")
            elif c1 or c2:
                ddx = ic(jf(24.0 * d))             # (int)(24 * dm.density)
                ddx = max(ddx, -x)
                if x + ddx + width > x + maxw:
                    ddx = ic(maxw - width)
                path = "C1" if c1 else "C2"
            elif e_g:
                ddx = _cl_center(s.w, width, x, maxw)
                path = "E"

        f_pred = (path == "none" and est > 0 and width > est
                  and not start_locked and x > 30
                  and s.w > jf(sw * 0.28) and s.w < jf(sw * 0.65)
                  and 96 <= s.h <= 130 and s.w > jf(est * 2.0))
        if f_pred:
            if not (tall or loose):
                text_px = max(text_px, base_px)
                padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
                padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
                text_w = measure(s.text, text_px)
                target = jf(jf(s.w - padh * 2.0) - 1.0)
                if text_w > target:
                    text_px = max(jf(10.0 * d),
                                  jfd(jf(text_px * target), text_w))
                    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(text_px * 0.4)))
                    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(text_px * 0.3)))
                    text_w = measure(s.text, text_px)
                width = s.w
                min_h = max(ic(jf(text_px) + padv * 2), rp(MIN_LINE_H_DP, d))  # MIN_SINGLE_LINE_HEIGHT_DP
                if min_h <= s.h:
                    height = min(s.h, max_pill_h)
                    ddy = jdiv(s.h - height, 2)
            ddx = jdiv(s.w - width, 2)
            ddx = max(ddx, -x)
            if x + ddx + width > x + maxw:
                ddx = ic(maxw - width)
            if path == "none":
                path = "F"
        log("gateF", (f_pred,), 0,
            "x=%d w=%d h=%d est=%d sl=%s" % (x, s.w, s.h, est,
                                             bool(start_locked)))

        # frame-1 profile fall-through (v2.10.45, fa10056)
        profile_hit = (frame1 and ddx == 0 and est > 0 and width > est
                       and s.vid and ctx.align.get(s.vid) == "PROFILE_CENTER")
        if profile_hit:
            ddx = _cl_center(s.w, width, x, maxw)
            path = "profile"
        log("frame1", (path == "profile",), 0,
            "path=%s width=%d est=%d" % (path, width, est))
    log("ddx", (ddx, path), 0, "path=%s" % path)

    # ---------------- vertical fine-tuning ---------------------------------
    if (multiline and wrap_lines == 1 and ddy == 0 and est > 0
            and s.w <= jf(est * 1.35) + 2 and height < s.h):
        ddy = jdiv(s.h - height, 2)
    if multiline and ddy == 0 and siblings is not None and allow_deep:
        y_top = s.y
        row_sibling = any(abs(t.y - y_top) <= rp(SAME_ROW_DY_DP, d)
                          for t in siblings if t is not s)
        gap_above = JMAX
        for t in siblings:
            if t is s:
                continue
            t_bottom = t.y + t.h
            if t_bottom > y_top or t.y <= y_top - nb_px:
                continue
            if t.x > x + width or t.x + t.w < x:
                continue
            up = compute_layout(t, word_wrap, siblings, ctx, None,
                                allow_deep=False, frame1=frame1)
            if up["hidden"]:
                continue
            up_x = t.x + up["ddx"]
            if up_x + up["width"] <= x:
                continue
            g = y_top - t_bottom
            if g < gap_above:
                gap_above = g
        if row_sibling:
            desired = jdiv(s.h - height, 2)
            if desired < 0 and (gap_above == JMAX or -desired <= gap_above):
                ddy = desired
                if y_top + ddy < 0:
                    ddy = -y_top
                if ddy + height > max_pill_h:
                    ddy = max_pill_h - height
                if ddy > 0:
                    ddy = 0
    log("ddy", (ddy,), 0, "h=%d node_h=%d ml=%s wrap=%d"
        % (height, s.h, multiline, wrap_lines))

    hidden = (not multiline and width > 0 and width < rp(MIN_PILL_DP, d)
              and text_w + padh * 2 > width)     # MIN_MEANINGFUL_PILL_DP px
    log("hidden", (hidden,), 0, "w=%d threshold=%d"
        % (width, rp(MIN_PILL_DP, d)))

    return dict(width=width, height=height, fs_px=text_px, padh=padh,
                padv=padv, multiline=multiline, ddx=ddx, ddy=ddy,
                path=path, hidden=hidden, preview=preview,
                wrap_lines=wrap_lines,
                band=bool(path == "band"))


def _cl_center(w, pw, x, maxw):
    ddx = jdiv(w - pw, 2)
    ddx = max(ddx, -x)
    if x + ddx + pw > x + maxw:
        ddx = ic(maxw - pw)
    return ddx


# ------------------------------ wrap helpers ===============================
def line_budget(box_h, fs, d):
    """Java lineBudget: (boxH - 2*padV)/lh + 1, clamped [2,3]; a JMAX box
    (no node below) yields a huge n -> 3."""
    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(fs * 0.3)))
    lh = ic(jf(fs * 1.25))
    if lh <= 0:
        return 2
    if box_h >= JMAX:
        return 3
    if box_h <= 0:
        return 2
    n = (box_h - padv * 2) // lh + 1
    return max(2, min(3, n))


def _words(text):
    out = []
    for part in text.split(" "):
        if len(part) > 1 and '-' in part:
            start = 0
            while True:
                h = part.find('-', start)
                if h < 0:
                    break
                out.append(part[start:h + 1])
                start = h + 1
            if start < len(part):
                out.append(part[start:])
        else:
            out.append(part)
    return out


def wrap_line_count(text, box_w, fs, max_lines, max_hpx, d):
    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(fs * 0.4)))
    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(fs * 0.3)))
    avail = jf(jf(box_w) - 2.0 * padh)
    if avail < fs:
        return 0
    lines = 1
    x = 0.0
    space_w = measure(" ", fs)
    for word in _words(text):
        ww = measure(word, fs)
        need = ww + (space_w if x > 0 else 0.0)
        if x + need > avail and x > 0:
            x = ww
            lines += 1
            if lines > max_lines:
                return 0
        else:
            x += need
        if x > avail:
            return 0
    h = jf(jf(lines * fs) * 1.25 + 2.0 * padv)
    if max_hpx < JMAX and h > jf(float(max_hpx) + 2.0):
        return 0
    return lines


def truncate_to_lines(text, box_w, fs, max_lines, max_hpx, d):
    """Java truncateToLines: the 2-3 line ellipsized preview. The ellipsis
    is reserved on every line (it lands on the last one), a segment wider
    than the reserved line is infeasible at this size, and the height cap
    is checked on the resulting block."""
    padh = max(rp(PADH_FLOOR_DP, d), ic(jf(fs * 0.4)))
    padv = max(rp(PADV_FLOOR_DP, d), ic(jf(fs * 0.3)))
    avail = jf(jf(box_w) - 2.0 * padh)
    if avail < fs:
        return None, 0
    pref = _prefix(text, fs)
    space_adv = fs * _units(' ')
    line_avail = jf(avail - measure("…", fs))
    lines = 1
    x = 0.0
    kept = []
    for s, e in _hyphen_splits(text):
        if e == s:                                # a bare space
            if x > 0 and x + space_adv > line_avail:
                if lines >= max_lines:
                    break
                lines += 1
                x = 0.0
            else:
                x += space_adv
            continue
        w = pref(e) - pref(s)
        if w > line_avail:
            return None, 0
        cost = w + (space_adv if x > 0 else 0.0)
        if x + cost > line_avail and x > 0:
            if lines >= max_lines:
                break
            lines += 1
            x = w
        else:
            x += cost
        kept.append(text[s:e])
    if len(kept) < 2 or lines < 2:
        return None, 0
    h = jf(jf(lines * fs) * 1.25 + 2.0 * padv)
    if max_hpx < JMAX and h > jf(float(max_hpx) + 2.0):
        return None, 0
    return " ".join(kept) + "…", lines
