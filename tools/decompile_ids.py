#!/usr/bin/env python3
"""Build a per-resource-id style map from a decompiled Deepal APK.

Unpacks the APK (apktool -s), resolves @dimen/... references, and scans
res/layout*.xml for every view that carries an id. For each id it records
the textSize (sp), horizontal gravity, horizontal padding (dp), and whether
the view is full-width (fill_parent/match_parent) in its layout — the exact
facts our overlay needs to replace the height/1.5 size estimate and the
px-calibrated anchoring heuristics.

Outputs:
  /tmp/deepal_id_styles.json          full map, id -> record
  /tmp/deepal_id_curated.json         compact, mergeable asset subset
  printed review for the runtime ids we already see in a11y dumps

Usage: python3 tools/decompile_ids.py /path/to/deepal.apk [apktool_dir]
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

OUT_STYLES = "/tmp/deepal_id_styles.json"
OUT_CURATED = "/tmp/deepal_id_curated.json"

# ids actually seen in the device a11y tree (this app build, v1.10.2)
RUNTIME_IDS = [
    "tvTopTitle", "tvTraffic", "tv_vin", "tvMykey", "tvControlCodeStatus",
    "tv_car_license_plate", "tv_car_belong", "tv_nickname", "viewCheckBox",
    "tvVersionTitle", "tvOtaVersionName", "toolBar", "nestedScrollView",
    "tvNotifyName", "tvNotifyDesc", "cbSwitchSet", "titleTv", "title_bar",
    "backIv", "back_click", "tab_text", "tabRootView", "tab_layout",
    "tv_ad_title", "tv_text", "tv_icon", "icon_text_badge_view", "img_icon",
    "txt_time", "txt_content", "tv_num", "img_message_type", "txt_user_name",
    "txt_title", "txt_follow", "txt_fans", "txt_collection", "txt_articles",
    "tv_sign", "tvMemberTaskDesc", "tvMemberTask", "tv_time", "tv_praises",
    "tv_name", "tv_content", "tv_comment", "tv_car_owner", "pag", "pos",
    "item_bg", "ex_icon", "v_status_bar", "tvVehicleSeries", "root",
    "rlContentView", "clOpenNotifySetting", "ll_vin_copy", "llTraffic",
    "ll_smart_watch", "llVehicleSeries",
]

A_NS = "http://schemas.android.com/apk/res/android"
FULL_WIDTH = ("fill_parent", "match_parent", "-1.0dip", "-1.0dp")
LEFT_GRAV = ("left", "start")
CENTER_GRAV = ("center", "center_horizontal")


def apktool_unpack(apk, dest):
    subprocess.run(["apktool", "d", "-s", "-f", apk, "-o", dest],
                   capture_output=True, text=True, timeout=600)
    if not os.path.isdir(os.path.join(dest, "res")):
        sys.exit("apktool unpack failed: res/ missing")


def id_of(node):
    v = node.get(f"{{{A_NS}}}id")
    m = re.match(r"@(?:\+)?id/(\w+)", v or "")
    return m.group(1) if m else None


def load_dimens(dest):
    """name -> {'sp': float | 'dp': float} across all values* configs."""
    out = {}
    base = os.path.join(dest, "res")
    for d in sorted(os.listdir(base)):
        if not d.startswith("values"):
            continue
        p = os.path.join(base, d, "dimens.xml")
        if not os.path.exists(p):
            continue
        try:
            tree = ET.parse(p)
        except ET.ParseError:
            continue
        for el in tree.getroot():
            if el.tag != "dimen":
                continue
            name = el.get("name")
            m = re.match(r"([\d.]+)(sp|dip|dp|px|pt)?", (el.text or "").strip())
            if not name or not m:
                continue
            val = float(m.group(1))
            unit = m.group(2)
            if unit == "sp":
                out[name] = {"sp": val}
            elif unit in ("dp", "dip", "px", "pt"):
                out[name] = {"dp": val}
    return out


def resolve_sp(value, dimens):
    """textSize attr -> sp float, resolving @dimen refs. None if unknown."""
    if value is None:
        return None
    v = value.strip()
    m = re.match(r"([\d.]+)sp$", v)
    if m:
        return float(m.group(1))
    m = re.match(r"@dimen/(\w+)$", v)
    if m and m.group(1) in dimens:
        sp = dimens[m.group(1)].get("sp")
        if sp is not None:
            return sp
    return None


def resolve_dp(value, dimens):
    """padding attr -> dp float, resolving @dimen refs. None if unknown."""
    if value is None:
        return None
    v = value.strip()
    m = re.match(r"([\d.]+)(?:dp|dip)$", v)
    if m:
        return float(m.group(1))
    m = re.match(r"@dimen/(\w+)$", v)
    if m and m.group(1) in dimens:
        return dimens[m.group(1)].get("dp")
    return None


def horiz_gravity(value):
    """Normalize an android:gravity to left / center / None (ambiguous).

    center_vertical alone carries no horizontal meaning (it is the default
    for a single-line layout) — only an explicit horizontal component counts.
    """
    if not value:
        return None
    parts = [p.strip() for p in value.split("|")]
    if any(p in CENTER_GRAV for p in parts):
        return "center"
    if any(p in LEFT_GRAV for p in parts):
        return "left"
    if any(p in ("right", "end") for p in parts):
        return "right"
    return None


def walk_view(node, styles, dimens):
    vid = id_of(node)
    if vid:
        rec = styles.setdefault(
            vid, {"layouts": set(), "sizes": set(), "grav": set(),
                  "padL": set(), "fullWidth": 0, "total": 0,
                  "hasCenter": False})
        lf = node.get("layout_file")
        if lf:
            rec["layouts"].add(lf)
        rec["total"] += 1
        sp = resolve_sp(node.get(f"{{{A_NS}}}textSize"), dimens)
        if sp:
            rec["sizes"].add(round(sp, 1))
        g = horiz_gravity(node.get(f"{{{A_NS}}}gravity"))
        if g:
            rec["grav"].add(g)
        # ANY layout with an explicit horizontal center => the id's text
        # alignment is NOT unambiguously start. Absent/vertical-only gravity
        # means "left by default" — the only safe start evidence.
        rawg = node.get(f"{{{A_NS}}}gravity") or ""
        if any(p.strip() in CENTER_GRAV for p in rawg.split("|")):
            rec["hasCenter"] = True
        for attr in ("paddingLeft", "paddingStart"):
            d = resolve_dp(node.get(f"{{{A_NS}}}{attr}"), dimens)
            if d is not None:
                rec["padL"].add(round(d, 1))
        w = (node.get(f"{{{A_NS}}}layout_width") or "").strip()
        if w in FULL_WIDTH or w == "0.0dip" or w == "0.0dp":
            rec["fullWidth"] += 1
    for child in list(node):
        if isinstance(child.tag, str):
            child.set("layout_file", node.get("layout_file"))
            walk_view(child, styles, dimens)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    apk = sys.argv[1]
    dest = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/deepal_real"
    if not os.path.isdir(os.path.join(dest, "res")):
        apktool_unpack(apk, dest)

    dimens = load_dimens(dest)
    print(f"dimens loaded: {len(dimens)}")

    layouts = []
    base = os.path.join(dest, "res")
    for sub in sorted(os.listdir(base)):
        if sub == "layout" or sub.startswith("layout"):
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                layouts += [os.path.join(d, f) for f in sorted(os.listdir(d))
                            if f.endswith(".xml")]

    styles = {}
    parsed = 0
    for path in layouts:
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        parsed += 1
        walk_view(tree.getroot(), styles, dimens)

    def norm(rec):
        sizes = sorted(rec["sizes"])
        # A single unique size (or a tight set) is the reliable one; an id
        # reused across many unrelated layouts with divergent sizes is
        # "ambiguous" for size purposes (the runtime bounds decide instead).
        size_sp = sizes[-1] if len(sizes) == 1 else (
            sizes if not sizes else None)
        grav = sorted(rec["grav"])
        grav = grav[0] if len(grav) == 1 else (
            {g for g in grav} if len(set(grav)) == 1 else None)
        return {
            "sp": size_sp,
            "grav": grav,
            "padLdp": sorted(rec["padL"]),
            "fullWidth": rec["fullWidth"],
            "occurrences": rec["total"],
            "layouts": sorted(rec["layouts"])[:12],
            # True when NO layout of this id declares a horizontal center
            # gravity. A pill on such a node may be LEFT-anchored
            # unconditionally — density-independent (the app's own layout
            # says the text is start-aligned).
            "startLock": not rec["hasCenter"],
        }

    full = {vid: norm(rec) for vid, rec in styles.items()}
    json.dump(full, open(OUT_STYLES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"layouts parsed: {parsed}, ids: {len(full)}")

    # Compact asset subset: ids with a definite single sp, PLUS ids that only
    # earn a start-lock flag (a layout size can be missing / set in code —
    # that does not make the text alignment ambiguous).
    curated = {}
    for vid, r in sorted(full.items()):
        has_sp = isinstance(r["sp"], (int, float))
        if not (has_sp or r["startLock"]):
            continue
        entry = {}
        if r["grav"]:
            entry["g"] = r["grav"]
        if r["padLdp"]:
            entry["p"] = r["padLdp"][-1]
        if r["fullWidth"] >= r["occurrences"] and r["occurrences"] >= 1:
            entry["fw"] = 1
        if r["startLock"]:
            entry["sl"] = 1
        if has_sp:
            curated[vid] = [float(r["sp"])] if not entry else [float(r["sp"]), entry]
        else:
            curated[vid] = [None, entry]  # size unknown, alignment known
    json.dump(curated, open(OUT_CURATED, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    locks = sum(1 for v in curated.values()
                if len(v) > 1 and isinstance(v[1], dict) and v[1].get("sl") == 1)
    print(f"curated ids: {len(curated)} (start-locks: {locks})")

    print("\n== runtime ids (seen in a11y) -> resolved style ==")
    for vid in RUNTIME_IDS:
        r = full.get(vid)
        if not r:
            print(f"  {vid:26s} -- not in layouts (programmatic/adapter) --")
            continue
        sp = r["sp"] if r["sp"] is not None else "amb"
        print(f"  {vid:26s} sp={str(sp):9s} grav={str(r['grav'] or '-'):7s} "
              f"padL={r['padLdp'] or '-'} fw={r['fullWidth']}/{r['occurrences']} "
              f"{'SL' if r['startLock'] else '  '}")


if __name__ == "__main__":
    main()
