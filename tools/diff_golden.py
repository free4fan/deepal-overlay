#!/usr/bin/env python3
"""Golden diff (brief prompt.md, step 1) — replaces pixel-based "хардгарды".

Compares two capture runs (dirs like tools/golden/<run>, each with
<screen>/{a11y.xml, overlays.txt, pills.json, screenshot.png, manifest.txt}).
The per-screen files come from tools/capture_golden.sh: a11y.xml = node
bounds (uiautomator), pills.json = the EXACT pill geometry the app itself
dumps while its dev golden flag is armed (overlay windows are invisible to
uiautomator/dumpsys — no package/title — so the app is the only
deterministic source).

HARD signals = the baseline->new DELTA (brief rules 3/5: «было/стало», any
non-target drift is a regression to justify in the CHANGELOG):
  * NODE-CHG  an a11y node moved/resized beyond +/-2px;
  * PILL-CHG  a pill's geometry RELATIVE TO ITS OWN NODE changed beyond
    +/-2px, appeared (NEW), or vanished (GONE). Relative-to-node by
    design: a whole-screen app scroll moves the node and its pill together
    and is not a layout regression.
No view_profiles involvement in the hard path -> a clean build's baseline
is always green.

ADVISORY (informational, not a gate): the absolute id-first coverage model
(profile g=center / p=padStart -> where the CJK run sits; label vs block;
overhang <=2px past the node frame). It is the input to step 3 (mixed-
gravity flagging) — today it also prints known code/profile contradictions
(e.g. tvTopTitle: profile g=center p=20dp, app places CJK at the ~56px
content edge) instead of asserting them as truth.

Usage:
  diff_golden.py BASELINE_DIR NEW_DIR [--json report.json]
Exit code: 0 = no hard deltas, 1 = hard deltas or PILL SOURCE MISSING.
"""
import json
import re
import sys
from pathlib import Path

TOL_PX = 2          # brief rule 4: CJK-box coverage margin invariant
MOVE_EPS_PX = 2     # bounds change above this is "moved"


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


def load_pills(path):
    """pills.json (app-golden-dump) -> [{key,id,text,node,pill,est,fsPx}].
    The deterministic source of pill geometry (overlay windows are
    invisible to uiautomator/dumpsys); produced by the app itself only
    while the dev flag is armed (invisible to the shipped build)."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
        out = []
        for e in data:
            if not isinstance(e, dict) or not e.get("pill"):
                continue
            out.append(e)
        return out
    except (FileNotFoundError, json.JSONDecodeError):
        return []


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


def coverage_model(node, est, sp, density, profile):
    """Deterministic coverage model (v1), id-first (brief prompt.md).
    node: rect; est: the app's CJK estimate for the node (px); sp: the
    node's estimated font (sp). The candidate CJK runs the pill MUST cover
    come from the view_profile of the id — the layout XML is the source of
    truth for where the CJK sits, not a guess:
      g == center   -> centered run (the app centers it)
      p (padStart)  -> content-edge run at x0 + p*density
      neither       -> BOTH the node-left and the centered run must be
                       covered (conservative fallback: unknown position)
    em for the run height = min(sp, 24)*density == the CJK glyph step that
    `est` was computed with, so coverage margins are measured in the same
    em the app used for width.
    A wider CJK (est >= 0.85*nodeW, e.g. a wrapping paragraph) is the block
    model: the pill must not escape the node's TOP/LEFT; growth down/right
    into the clear gap below is allowed (reported).
    overhang invariant (label): the pill must not exceed the node's own
    frame by > OVERHANG_MAX px on any side.
    """
    x0, y0, x1, y1 = node
    nw, nh = x1 - x0, y1 - y0
    em = min(max(10.0, (sp or 24.0)), 24.0) * density
    est_w = est if est and est > 0 else nw
    gy = y0 + max(0, (nh - int(em)) // 2)
    gcenter = (profile or {}).get("g") == "center"
    pad_dp = (profile or {}).get("p")
    runs = []
    if est_w < 0.85 * nw:                     # label
        w = min(int(est_w), nw)
        if gcenter:
            cx = x0 + (nw - w) // 2
            runs.append((cx, gy, cx + w, gy + int(em)))
        elif pad_dp is not None:
            ex = x0 + int(pad_dp * density)
            runs.append((ex, gy, ex + w, gy + int(em)))
        else:                                 # unknown position -> cover both
            runs.append((x0, gy, x0 + w, gy + int(em)))
            cx = x0 + (nw - w) // 2
            if cx != x0:
                runs.append((cx, gy, cx + w, gy + int(em)))
        return {"model": "label", "runs": runs, "est": int(est_w),
                "pos": "center" if gcenter else
                        ("edge+%.0fpx" % (pad_dp * density)
                         if pad_dp is not None else "left+center")}
    return {"model": "block", "runs": [(x0, y0, x1, y1)], "est": int(est_w),
            "pos": "fill"}


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

        # ---- pill coverage: HARD = baseline->new DELTA (brief rules 3/5:
        # "было/стало", any non-target drift = regression); profile-free so a
        # clean v-code baseline is always green. Advisory = the absolute
        # id-first model (g/p from view_profiles) — informational input to
        # step 3 (mixed-gravity), NOT a hard gate while the profile is
        # known-incomplete (e.g. tvTopTitle: profile g=center, p=20dp while
        # the app places the CJK at the ~56px content edge — a mixed case).
        pills_n = load_pills(new_dir / s / "pills.json")
        pills_b = load_pills(base_dir / s / "pills.json")
        src = "app-dump" if (pills_n or pills_b) else "MISSING"
        ent["pill_source"] = src
        if src == "MISSING":
            hard_fail = True
            ent["note"] = ("no pills.json in either run — arm the app golden "
                           "dump (debug build + tools/capture_golden.sh); "
                           "pill geometry unavailable")
        ent["coverage_new"] = {}
        # Pills move WITH their node on an app scroll, so (id,text) is the
        # stable identity, not the node position. Baseline map keyed by
        # (id, text); on a duplicate (same id+text twice on one screen, e.g.
        # nav tab labels) keep them in a list and disambiguate by nearest
        # node position.
        bmap = {}
        for p in pills_b:
            bmap.setdefault((p.get("id", ""), p.get("text", "")), []).append(p)
        used = set()

        def nearest_baseline(p):
            cands = bmap.get((p.get("id", ""), p.get("text", "")), [])
            best, bd = None, 1e18
            for c in cands:
                if id(c) in used:
                    continue
                cn = c["node"]; dn = p["node"]
                dd = sum((a - b) ** 2 for a, b in zip(cn, dn))
                if dd < bd:
                    best, bd = c, dd
            return best

        # hard signals: node-relative pill geometry delta
        for p in pills_n:
            node, pill = tuple(p["node"]), tuple(p["pill"])
            rel = (pill[0] - node[0], pill[1] - node[1],
                   node[2] - pill[2], node[3] - pill[3])
            ob = nearest_baseline(p)
            drift = None
            if ob is None:
                drift = "NEW (no baseline pill with id+text %s)" % (
                    (p.get("id", "") or p.get("text", "")[:8],))
            else:
                used.add(id(ob))
                on, op = tuple(ob["node"]), tuple(ob["pill"])
                ores = (op[0] - on[0], op[1] - on[1],
                        on[2] - op[2], on[3] - op[3])
                d = [rel[i] - ores[i] for i in range(4)]
                if max(abs(v) for v in d) > TOL_PX:
                    drift = "pill moved relative to node d(L,T,R,B)=%s " \
                            "(was %s)" % (d, ores)
            # advisory absolute model
            est = int(p.get("est", 0) or 0)
            sp = float(p.get("sp", 0) or 0) or 24.0
            prof = profile_flags(p.get("id", "")) if p.get("id") else {}
            nobj = {"b": node, "text": p.get("text", ""), "id": p.get("id", "")}
            model = coverage_model(node, est, sp, dens, prof)
            aok, areasons, anums = check_coverage(pill, nobj, model)
            key = "%s|%.16s" % (p.get("id", "") or p.get("text", "")[:8],
                                p.get("text", ""))
            ent["coverage_new"][key] = {
                "drift": drift, "node": list(node), "pill": list(pill),
                "rel_L_TR_B": rel, "est": est, "sp": sp,
                "model": model["model"], "pos": model["pos"],
                "profile": dict(prof), "overhang": anums,
                "advisory_ok": aok, "advisory_reasons": areasons}
        for p in pills_b:
            if id(p) in used:
                continue
            key = "%s|%.16s|gone" % (p.get("id", "") or p.get("text", "")[:8],
                                     p.get("text", ""))
            ent["coverage_new"][key] = {
                "drift": "GONE (was in baseline)", "node": list(p["node"]),
                "pill": list(p["pill"]), "rel_L_TR_B": None,
                "est": int(p.get("est", 0) or 0), "sp": 0.0,
                "model": "?", "pos": "?", "profile": {}, "overhang": {},
                "advisory_ok": False,
                "advisory_reasons": ["pill disappeared"]}

    print("GOLDEN DIFF  baseline=%s  new=%s" % (base_dir, new_dir))
    hard_n = 0
    for s, ent in report["screens"].items():
        if "status" in ent:
            print("  [%s] %s" % (s.upper(), ent["status"]))
            continue
        moved = ent["nodes_moved"]
        print("  [%s] nodes moved: %d   pill_source: %s"
              % (s, len(moved), ent.get("pill_source")))
        for m in moved[:15]:
            extra = m["d(x,y,w,h)"] if "d(x,y,w,h)" in m else m["was"]
            print("    - NODE-CHG %s %s %r -> %s" % (
                m["kind"], m["node"], m["text"], extra))
            hard_n += 1
        for k, v in sorted(ent["coverage_new"].items()):
            if v["drift"]:
                print("    - PILL-CHG %s  %s  rel=%s" % (k, v["drift"],
                                                         v["rel_L_TR_B"]))
                hard_n += 1
            if not v["advisory_ok"]:
                print("      ~ advisory(profile) %s model=%s pos=%s %s" % (
                    k, v["model"], v["pos"], v["advisory_reasons"][:1]))
        if ent.get("note"):
            print("    ! " + ent["note"])
    print("HARD signals (baseline->new deltas): %d" % hard_n)
    print("RESULT: %s" % ("HARD-FAIL" if (hard_fail or hard_n) else "clean"))
    if out_json:
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print("json ->", out_json)
    sys.exit(1 if (hard_fail or hard_n) else 0)


if __name__ == "__main__":
    main()
