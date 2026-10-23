#!/usr/bin/env python3
"""T-36a iteration 3 (contract: DESIGN.md «КОНТРАКТ Т-36a итерации №3»,
10-23) — READ-ONLY baseline probe.

Classifies the RU-text gravity of every EMPTY-ID a11y node on the
canonical baseline (pre_step4_96_7282, d2.25) by measuring the white
RU text inside its baseline pill (white-on-dark) — the fact the overlay
actually rendered. Contract rule (deterministic, written BEFORE this
probe):

    p = baseline pixels, d2.25
    left / right  = white-ru-text offset from the pill edges
    padH          = int(0.4 * fsPx)          (IOM:623, same as runtime)
    left <= padH + 10                                  -> start
    |left-right| <= max(10, 0.2*max) AND min >= padH+14  -> center
    else                                               -> ambiguous

Output: tools/golden/empty_id_align_draft.json  (ONLY start/center;
ambiguous and degenerate excluded — they keep the length heuristic)
plus a printed table. No files outside tools/golden/ are touched.

Usage: python3 tools/_annotate_emptyid_align.py
"""
import glob
import json
import re
import sys
from pathlib import Path

import importlib.util
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location("ds", str(Path(__file__).resolve().parent / "density_sweep.py"))
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

BASE = "tools/golden/pre_step4_96_7282"
D = 2.25
OUT = "tools/golden/empty_id_align_draft.json"


def est_w(text, fs_sp):
    """Runtime CJK estimate (TranslationService.estimateSourceWidth)."""
    em = max(10.0, min(float(fs_sp), 24.0)) * D
    w = 0.0
    for c in text:
        o = ord(c)
        wide = (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
                or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
                or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60
                or 0xD800 <= o <= 0xDFFF)
        w += em if wide else em * 0.55
    return max(1, int(w + 0.5))


def a11y_nodes(path):
    raw = open(path, encoding="utf-8").read()
    nodes = []
    for m in re.finditer(r"<node ([^>]*)/>|<node ([^>]*)>", raw):
        h = m.group(1) or m.group(2)

        def g(k, _h=h):
            mm = re.search(k + r'="([^"]*)"', _h)
            return mm.group(1) if mm else ""

        text, rid, cls = g("text"), g("resource-id"), g("class")
        mm = re.findall(r"-?\d+", g("bounds"))
        if len(mm) == 4 and cls.endswith("TextView") and text:
            x0, y0, x1, y1 = (int(c) for c in mm)
            if x1 - x0 > 0 and y1 - y0 > 0:
                nodes.append({"text": text,
                              "id": rid.split("/")[-1] if rid else "",
                              "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return nodes


def ru_span(px, pill):
    """White-text (r,g,b all >185) horizontal span inside the pill."""
    x, y, pw, ph = pill
    best = None
    for yy in range(y + 12, y + ph - 8, 2):
        left = right = None
        for xx in range(x + 3, x + pw - 3):
            r, gg, b = px[xx, yy]
            if r > 185 and gg > 185 and b > 185:
                if left is None:
                    left = xx
                right = xx
        if left is not None and (best is None or right - left > best[1] - best[0]):
            best = (left, right)
    if not best:
        return None
    x, y, pw, ph = pill
    return (best[0] - x, (x + pw) - best[1])


def half_dp(v):
    """dp value on the half-dp grid (d2.25), Java String.valueOf formatted:
    no trailing .0 (320, not 320.0) — mirrors the Android side float parse."""
    dp = round(v / D * 2) / 2
    return "%d" % int(dp) if dp == int(dp) else "%s" % repr(dp)


def exact_key(n):
    return "%s|%sx%s" % (n["text"], half_dp(n["x1"] - n["x0"]),
                         half_dp(n["y1"] - n["y0"]))


# Layout-oracle set (DESIGN.md §contract №3, 10-23): nodes whose app gravity
# is KNOWN from the decompiled layout (/tmp/deepal_res_dec). All listed labels
# are TextViews with NO horizontal gravity attribute in
# res/layout/activity_my_car_setting.xml (= app START alignment; the only
# gravity on them is center_vertical = vertical). The probe's rendered
# CENTER verdict on 爱车昵称/车牌号 is the overlay's own bug (the length
# heuristic fired) — the app fact is START, hence ORACLE_START.
ORACLE_START = set("爱车昵称 车牌号 车架号 车载娱乐流量 钥匙管理 智能手表 3D车模".split())
ORACLE_CENTER = set()


rows = []
screens = sorted(Path(p).parent.name for p in
                 glob.glob(BASE + "/*/a11y.xml"))
assert screens, "no baseline screens found: " + BASE

for scr in screens:
    nodes = a11y_nodes(BASE + "/" + scr + "/a11y.xml")
    try:
        pills = {tuple(e["node"]): (e.get("text") or "", e["pill"])
                 for e in json.load(open(BASE + "/" + scr + "/pills.json"))}
    except Exception:
        continue
    try:
        px = Image.open(BASE + "/" + scr + "/screenshot.png").convert("RGB").load()
    except Exception:
        continue
    for n in nodes:
        if n["id"]:
            continue  # id-keyed: the profile governs, not this annotation
        key = (n["x0"], n["y0"], n["x1"], n["y1"])
        ru, pill = pills.get(key, (None, None))
        if ru is None or pill is None:
            rows.append((scr, n, None, None, None, "no-baseline-pill", ""))
            continue
        w, h = n["x1"] - n["x0"], n["y1"] - n["y0"]
        fs_sp = max(10.0, min(h / D * (2.0 / 3.0), 24.0))
        padh = int(fs_sp * D * 0.4)          # IOM:623 (0.4*textSizePx)
        span = ru_span(px, pill)
        if span is None:
            rows.append((scr, n, ru, w, h, "no-white-text", ""))
            continue
        left, right = span
        pw = pill[2]
        # contract rule
        if left <= padh + 10:
            cls = "start"
        elif abs(left - right) <= max(10, 0.2 * max(left, right)) \
                and min(left, right) >= padh + 14:
            cls = "center"
        else:
            cls = "ambiguous"
        degenerate = (left + right) < 2 * (padh + 14)
        rows.append((scr, n, ru, w, h, cls,
                     "DEGENERATE" if degenerate else ""))

print("%-15s %-26s %30s %-9s %s" %
      ("screen", "EXACT key (text|dpbox)", "RU", "verdict", "note"))
data = {}
keys = set()
for scr, n, ru, w, h, cls, note in rows:
    key = exact_key(n)
    print("%-15s %-26s %30s %-9s %s" %
          (scr, key[:26], (ru or "-")[:30], cls, note))
    if key in keys:
        continue
    keys.add(key)
    # final data = the LAYOUT-ORACLE set (DESIGN §contract №3): the nodes
    # whose app gravity is known from the decompiled layout (no horizontal
    # gravity attr = start). The other probe verdicts stay heuristic.
    if n["text"] in ORACLE_START:
        data[key] = "start"
    elif n["text"] in ORACLE_CENTER:
        data[key] = "center"

print()
print("verdicts: center=%d start=%d ambiguous=%d no-pill=%d other=%d" % (
    sum(1 for r in rows if r[5] == "center"),
    sum(1 for r in rows if r[5] == "start"),
    sum(1 for r in rows if r[5] == "ambiguous"),
    sum(1 for r in rows if r[5] == "no-baseline-pill"),
    sum(1 for r in rows if r[5] not in ("center", "start", "ambiguous", "no-baseline-pill"))))
json.dump(data, open(OUT, "w"), ensure_ascii=False, indent=1, sort_keys=True)
print("data written: " + OUT + "  (%d nodes)" % len(data))
