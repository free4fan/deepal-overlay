#!/usr/bin/env python3
# Per-density internal dump for the 5 residual dx nodes (T-35 remainder).
# Reproduces the mirror's intermediate state (sibling pass, shape, font
# branch, width-side areas, height-side terms) so the deviation pattern
# can be attributed: px-constant vs int-quantization vs text-model.
import sys, importlib.util
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import density_sweep_mir as M
import density_sweep as ds

BASE = Path(__file__).parent / "golden" / "pre_step4_96_7282"
DENS = (1.0, 1.5, 2.0, 2.25, 2.75, 3.0, 3.5, 4.0)

def probe(scr, txt, side):
    pills = ds.load_screen(BASE / scr)
    slopes, kinds = ds.build_slopes(pills)
    M.set_text_slopes(slopes)
    p = [q for q in pills if (q.get("text") or "").startswith(txt)][0]
    base_node = (round(p["node"][0] * 2.25 / 2.25), round(p["node"][1] * 2.25 / 2.25))
    print("=" * 100)
    print("%s  %r  node@2.25=%s est=%s" % (scr, (p.get("text") or "")[:30], p["node"], p.get("est")))
    for d in DENS:
        specs = ds.scale(pills, d)
        bag = ds._DenseBag(d, *ds.load_profile())
        sw, sh = ds.scale_screen(d)
        rh = ds.screen_real_h(specs)
        ctx = M.Ctx(d, sw, rh, bag.align, bag.start_locked, bag.font_sp)
        tx = round(p["node"][0] * d / 2.25); ty = round(p["node"][1] * d / 2.25)
        s = [q for q in specs if (q.x, q.y) == (tx, ty)][0]
        trail = []
        out = M.compute_layout(s, False, specs, ctx,
                               allow_deep=True, frame1=False, trail=trail)
        # sibling pass (mirror lines 286-318)
        edge = M.rp(M.EDGE_MARGIN_DP, d); nb = M.rp(M.NEIGHBOR_MAX_DP, d)
        same = M.rp(M.SAME_ROW_DY_DP, d); gap = M.rp(M.ROW_GAP_DP, d)
        near_thr = M.rp(M.NEAR_ROW_DP, d)
        maxw = max(near_thr, sw - s.x - edge); close_row = False
        gap_below = -1
        for t in specs:
            if t is s:
                continue
            dx = t.x - s.x; dyb = t.y - s.y
            if 0 < dx < nb and abs(t.y - s.y) <= same:
                close_row = True
            if 0 < dyb < nb and t.x < s.x + maxw and t.x + t.w > s.x:
                g = t.y - (s.y + s.h)
                if gap_below < 0 or g < gap_below:
                    gap_below = g
        maxp = s.h + M.ic(M.jf(max(0, gap_below) * 0.75)) if gap_below >= 0 else M.JMAX
        # estimate
        est_sp = min(24.0, max(10.0, s.sp)) if s.sp > 0 else 0.0
        est_px = M.jf(est_sp * d)
        est_px = max(M.jf(10.0 * d), min(est_px, M.jf(24.0 * d)))
        shp = [e for e in trail if e["cond"] == "shape"][0]["value"]
        ff = [e for e in trail if e["cond"] == "fontFit"][0]
        ffdetail = ff["detail"]
        # width-side areas (simple / not-tall-only terms)
        tp = out["fs_px"]; padh = out["padh"]; padv = out["padv"]
        tw = M.measure(out["preview"] or s.text, tp) if out.get("preview") \
            else M.measure(s.text, tp)
        text_area = min(M.ic(tw), maxw - padh * 2)
        node_area = min(M.ic(s.w), maxw - padh * 2)
        # expected simple plain height (else branch)
        h_plain = s.h + padv * 2
        min_h = max(M.ic(M.jf(tp) + padv * 2), M.rp(M.MIN_LINE_H_DP, d))
        dev = out[side] / d - out[side] / 2.25 * (1.0)  # placeholder, compute below
        base = out["base"] if "base" in out else None
        print("  d=%.2f node=(%3d,%3d)x(%3d,%3d) s.h=%3d est=%4d estPx=%7.2f close=%s gap_b=%4d maxP=%4d"
              % (d, s.x, s.y, s.w, s.h, s.h, s.est, est_px, close_row, gap_below,
                 M.JMAX // 2 if maxp > M.JMAX // 2 else maxp))
        print("        shape=%s fontFit(ML,wrap,fs)=%s fs=%6.2f padh=%2d padv=%2d  %s"
              % (shp, ff["value"], tp, padh, padv, ffdetail))
        if side == "width":
            print("        W: maxw=%4d textW=%6.2f textA=%5d nodeA=%5d -> width=%4d (plain h=%3d minH=%3d)"
                  % (maxw, tw, text_area, node_area, out["width"], h_plain, min_h))
        else:
            print("        H: h=%3d plain(s.h+2p)=%3d minH=%3d  multiline=%s wrap_lines=%d"
                  % (out["height"], h_plain, min_h, out["multiline"], out["wrap_lines"]))

if __name__ == "__main__":
    probe("mashina_scroll", "Быстрый холод", "height")
    probe("service_deepal_grid", "Моб. интернет", "height")
    probe("explore", "Фестиваль двойной", "height")
    probe("my_tab", "Вы получите 2 очка", "height")
    probe("trip_info", "Deepal был с тобой", "width")
    print("done")
