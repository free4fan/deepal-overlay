#!/usr/bin/env python3
"""Golden diff (brief prompt.md, step 1) — replaces pixel-based "хардгарды".

Compares two capture runs of the same screen list (dirs like
tools/golden/<run>, each with <screen>/a11y.xml + overlays.txt and a
manifest.txt) and reports, per screen:
  * app nodes whose bounds changed (delta px) — "регрессия ≠ изменение":
    any non-target change here must be justified in the CHANGELOG
  * per pill: coverage of the CJK run it replaces (brief rule 4,
    reformulated from px snapshots to invariants):
      label model (short CJK inside a wider node — dialog/action buttons,
        icon tiles): the pill must cover the CJK run in BOTH its possible
        positions (node-left and node-center — position is only known from
        the g flag in view_profiles) AND must not overhang the node's own
        frame by more than OVERHANG_MAX px on any side (the «pill must not
        escape the button frame» invariant).
      block model (CJK fills/wraps the node — paragraphs): the pill must
        not escape the node's TOP or LEFT edge (top-anchored wrap); the
        gap below the node is free screen estate, growth there is allowed
        and reported, never failed (the «8-я строка режется / превью …»
        class of defects becomes a diffable number).
    No raw «211×64 @ y1120» hardguards anywhere — only these checks.

Pill rect sources, per run (flagged in report, first available wins):
  1. a11y.xml nodes of package com.walter.overlay
  2. com.walter.overlay windows from overlays.txt (dumpsys)
If neither yields pills -> "PILL SOURCE MISSING" hard-fail (visible on
the first run, not silently).

Usage:
  diff_golden.py BASELINE_DIR NEW_DIR [--json report.json]
"""
import json
import re
import sys
from pathlib import Path

TOL_PX = 2          # brief rule 4: CJK-box coverage margin invariant
MOVE_EPS_PX = 2     # bounds change above this is "moved"

CJK_RANGES = ((0x1100, 0x115F), (0x2E80, 0xA4CF), (0xAC00, 0xD7A3),
              (0xF900, 0xFAFF), (0xFE30, 0xFE4F), (0xFF00, 0xFF60),
              (0xD800, 0xDFFF))


def est_width(text, density, em_sp):
    """Mirror of TranslationService.estimateSourceWidth (deterministic)."""
    em = max(10.0, min(em_sp, 24.0)) * density
    w = 0.0
    for ch in text:
        cp = ord(ch)
        wide = any(a <= cp <= b for a, b in CJK_RANGES)
        w += em if wide else em * 0.55
    return max(1, int(w + 0.5))


def load_nodes(path):
    """a11y.xml -> [{id,text,cls,pkg,b:(x0,y0,x1,y1)}]."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    out = []
    for m in re.finditer(
            r'text="([^"]*)"[^>]*?resource-id="([^"]*)"[^>]*?'
            r'class="([^"]*)"[^>]*?package="([^"]*)"[^>]*?'
            r'bounds="(\[\d+,\d+\]\[\d+,\d+\])"', raw):
        text, rid, cls, pkg, b = m.groups()
        n = [int(v) for v in re.findall(r"\d+", b)]
        if len(n) == 4:
            out.append({"id": rid.rsplit("/", 1)[-1] if rid else "",
                        "text": text, "cls": cls, "pkg": pkg, "b": tuple(n)})
    return out


PROFILE_PATH = Path(__file__).resolve().parent.parent / \
    "app/src/main/assets/view_profiles.json"
_PROFILES = None


def profiles():
    global _PROFILES
    if _PROFILES is None:
        try:
            _PROFILES = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _PROFILES = {}
    return _PROFILES


def profile_flags(view_id):
    v = profiles().get(view_id)
    if isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict):
        return v[1]
    return {}


def load_pkg_windows(path, pkg):
    """overlays.txt (dumpsys window windows) -> [(x0,y0,x1,y1)] for pkg.
    dumpsys formats vary; accept bounds near the package name on the line
    or the next (Window{...}/Frames lines)."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    out = []
    lines = raw.splitlines()
    for i, ln in enumerate(lines):
        if pkg not in ln:
            continue
        scope = ln + " " + "\n".join(lines[i + 1:i + 3])
        for m in re.finditer(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", scope):
            x0, y0, x1, y1 = map(int, m.groups())
            if (x1 - x0) >= 20 and (y1 - y0) >= 20:
                out.append((x0, y0, x1, y1))
    return out


def density(dump_path, fallback=2.25):
    try:
        raw = dump_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"phys=(\d+)x(\d+)[^;\n]*?(?:xdpi|dpi)[:= ]?(\d+)", raw)
        if m:
            dpi = int(m.group(3))
            if dpi:
                return dpi / 160.0
    except FileNotFoundError:
        pass
    return fallback


def coverage_model(node, density, profile):
    """Deterministic coverage model (v1).
    est_w = width of the node's source CJK at the 24sp cap (app formula).
      label : est_w < 0.85·nodeW — a short CJK run inside a wider node
              (dialog/action buttons, icon tiles). The run may sit at the
              node's left (app default) or centered (buttons/profile
              g=center); the invariant: the pill covers BOTH candidates
              (union) AND does not overhang the node frame by > OVERHANG
              on any side (the «pill must not escape the button frame»
              invariant, expressed without px snapshots).
      block : est_w ≥ 0.85·nodeW — the CJK fills/wraps the node (content
              paragraphs). The invariant: the pill may not escape the
              node's TOP or LEFT (top-left/center-top anchored), i.e. the
              CJK block is not revealed above/left of the pill; growing
              down/right into the clear gap below is allowed (reported).
    profile: view_profiles entry (dict) or None; only g=center is used.
    """
    x0, y0, x1, y1 = node["b"]
    nw, nh = x1 - x0, y1 - y0
    em = min(24.0, 24.0) * density  # 24sp cap, sp->px
    est_w = est_width(node["text"], density, 24.0)
    gy = y0 + max(0, (nh - int(em)) // 2)
    runs = []
    if est_w < 0.85 * nw:                     # label
        w = min(est_w, nw)
        runs.append((x0, gy, x0 + w, gy + int(em)))               # left
        cx = x0 + (nw - w) // 2
        if cx != x0:
            runs.append((cx, gy, cx + w, gy + int(em)))           # center
        return {"model": "label", "runs": runs, "est": est_w,
                "centered_profile": (profile or {}).get("g") == "center"}
    return {"model": "block", "runs": [(x0, y0, x1, y1)], "est": est_w,
            "centered_profile": (profile or {}).get("g") == "center"}


OVERHANG_MAX = 2  # px the pill may exceed the app node's own frame


def check_coverage(pill, node, model):
    """Returns (ok, reasons[], numbers for the report)."""
    px0, py0, px1, py1 = pill
    nb = node["b"]
    nums = {"overhang_L": max(0, nb[0] - px0), "overhang_T": max(0, nb[1] - py0),
            "overhang_R": max(0, px1 - nb[2]), "overhang_B": max(0, py1 - nb[3])}
    # overhang can also be negative-pill-side: pill starts left of node =
    # overhang_L>0 covers it; symmetric for T/R/B.
    reasons = []
    if model["model"] == "label":
        for i, r in enumerate(model["runs"]):
            m = (r[0] - px0, r[1] - py0, px1 - r[2], py1 - r[3])
            if any(v < -TOL_PX for v in m):
                reasons.append("CJK run %d (left/center) not covered: "
                               "margins(L,T,R,B)=%s" % (i, list(m)))
        if max(nums.values()) > OVERHANG_MAX:
            reasons.append("pill overhangs the node frame: %s"
                           % {k: v for k, v in nums.items() if v > OVERHANG_MAX})
    else:  # block
        if nums["overhang_L"] > OVERHANG_MAX:
            reasons.append("pill left edge escapes node left by %d"
                           % nums["overhang_L"])
        if nums["overhang_T"] > OVERHANG_MAX:
            reasons.append("pill top edge escapes node top by %d"
                           % nums["overhang_T"])
    return (not reasons), reasons, nums


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    base_dir, new_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_json = (Path(sys.argv[sys.argv.index("--json") + 1])
                if "--json" in sys.argv else None)

    def screen_list(d):
        man = d / "manifest.txt"
        if man.exists():
            return [l.split("=", 1)[1].strip()
                    for l in man.read_text().splitlines()
                    if l.startswith("screen=")]
        return sorted(p.name for p in d.iterdir() if p.is_dir())

    s_base, s_new = set(screen_list(base_dir)), set(screen_list(new_dir))
    report = {"baseline": str(base_dir), "new": str(new_dir), "screens": {}}
    hard_fail = False

    for s in sorted(s_base | s_new):
        ent = report["screens"].setdefault(s, {})
        if s not in s_new:
            ent.update(status="REMOVED")
            continue
        if s not in s_base:
            ent.update(status="ADDED")
            continue
        nb = load_nodes(base_dir / s / "a11y.xml")
        nn = load_nodes(new_dir / s / "a11y.xml")
        dens = density(new_dir / s / "overlays.txt") or \
            density(base_dir / s / "overlays.txt")
        ent.update(nodes_moved=[], coverage_new={})

        used = set()
        moved = ent["nodes_moved"]
        for n in nb:
            best, best_d, best_i = None, 1e18, -1
            for j, m in enumerate(nn):
                if j in used:
                    continue
                if m["id"] != n["id"] and m["cls"] != n["cls"]:
                    continue
                if m["text"] != n["text"]:
                    continue
                d = sum((a - b) ** 2 for a, b in
                        zip((sum(n["b"][::2]), sum(n["b"][1::2])),
                            (sum(m["b"][::2]), sum(m["b"][1::2]))))
                if d < best_d:
                    best, best_d, best_i = m, d, j
            if best is None:
                moved.append({"node": n["id"] or n["cls"],
                              "text": n["text"][:20], "kind": "GONE",
                              "was": list(n["b"])})
                continue
            used.add(best_i)
            d = [best["b"][k] - n["b"][k] for k in (0, 1)] + \
                [(best["b"][2] - best["b"][0]) - (n["b"][2] - n["b"][0]),
                 (best["b"][3] - best["b"][1]) - (n["b"][3] - n["b"][1])]
            if max(abs(v) for v in d) > MOVE_EPS_PX:
                moved.append({"node": best["id"] or best["cls"],
                              "text": best["text"][:20], "kind": "MOVED",
                              "d(x,y,w,h)": d, "was": list(n["b"]),
                              "now": list(best["b"])})

        pills_a11y = [n["b"] for n in nn if n["pkg"] == "com.walter.overlay"]
        pills_dmp = load_pkg_windows(new_dir / s / "overlays.txt",
                                     "com.walter.overlay")
        src = "a11y" if pills_a11y else ("dumpsys" if pills_dmp else "MISSING")
        ent["pill_source"] = src
        if src == "MISSING":
            hard_fail = True
            ent["note"] = ("no pill windows in a11y.xml or dumpsys for this "
                           "screen — pill geometry unavailable (visible gap, "
                           "fix source next)")
        pill_rects = pills_a11y or pills_dmp
        cov = ent["coverage_new"]
        for n in nn:
            if n["pkg"] == "com.walter.overlay" or not n["text"]:
                continue
            prof = profile_flags(n["id"]) if n["id"] else {}
            model = coverage_model(n, dens, prof)
            best = None  # (score, pill, reasons)
            for p in pill_rects:
                ox = min(p[2], n["b"][2]) - max(p[0], n["b"][0])
                if ox <= 0:
                    continue  # this pill does not sit on this node
                ok, reasons, nums = check_coverage(p, n, model)
                score = sum(nums.values())
                if best is None or score < best[0]:
                    best = (score, p, reasons, nums)
            key = "%s|%.16s" % (n["id"] or n["cls"], n["text"])
            cov[key] = {
                "model": model["model"],
                "profile": {k: v for k, v in prof.items()},
                "cjk_runs": [list(r) for r in model["runs"]]
                if model["model"] == "label" else [list(n["b"])],
                "pill": list(best[1]) if best else None,
                "overhang": best[3] if best else None,
                "ok": bool(best and not best[2]),
                "reasons": best[2] if best else ["pill missing for node"]}

    print("GOLDEN DIFF  baseline=%s  new=%s" % (base_dir, new_dir))
    for s, ent in report["screens"].items():
        if "status" in ent:
            print("  [%s] %s" % (s.upper(), ent["status"]))
            continue
        print("  [%s] nodes moved: %d   pill_source: %s"
              % (s, len(ent["nodes_moved"]), ent.get("pill_source")))
        for m in ent["nodes_moved"][:15]:
            extra = m["d(x,y,w,h)"] if "d(x,y,w,h)" in m else m["was"]
            print("    - %s %s %r -> %s" % (m["kind"], m["node"],
                                            m["text"], extra))
        fails = {k: v for k, v in ent["coverage_new"].items() if not v["ok"]}
        for k, v in list(fails.items())[:15]:
            print("    ! COVERAGE-FAIL %s  model=%s overhang=%s"
                  % (k, v["model"], v["overhang"]))
            for r in v["reasons"][:3]:
                print("        - " + r)
        if ent.get("note"):
            print("    ! " + ent["note"])
    print("RESULT: %s" % ("HARD-FAIL" if hard_fail else "complete"))
    if out_json:
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print("json ->", out_json)
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
