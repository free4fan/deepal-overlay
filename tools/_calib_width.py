#!/usr/bin/env python3
"""Width-equation audit: which formula generated the dump's single-line
pill widths — H1 w = W1 + 2·ic(0.4·fs) (the mirror's) vs node-hug — and
does W1/fs stay constant per text across DIFFERENT device font sizes
(the one available hard consistency check for a real-font W1)?"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import density_sweep_mir as M  # noqa: E402


def padh(fs):
    return max(4, M.ic(M.jf(fs * 0.4)))


def padv(fs):
    return max(2, M.ic(M.jf(fs * 0.3)))


def single_line_h(fs):
    return max(max(M.ic(M.jf(fs * 1.25)) * 1 + 2 * padv(fs), 20),
               M.ic(M.jf(fs)) + 2 * padv(fs))


slopes = defaultdict(list)     # text -> [(fs, W1, screen, id, src)]
fits = defaultdict(int)
for scr in sorted(d.name for d in
                  (ROOT / "golden/pre_step4_96_7282").iterdir()
                  if d.is_dir()):
    for p in json.loads((ROOT / "golden/pre_step4_96_7282" / scr
                         / "pills.json").read_text()):
        if len(p.get("node", [])) != 4:
            continue
        fs = p.get("fsPx") or 0
        if not fs:
            continue
        w, h = p["pill"][2], p["pill"][3]
        nw, nh = p["node"][2] - p["node"][0], p["node"][3] - p["node"][1]
        lh = M.ic(M.jf(fs * 1.25))
        min_h = max(M.ic(M.jf(fs)) + 2 * padv(fs), 20)
        if h >= 2 * lh + 2 * padv(fs):      # ≥2 lines: not a width pin
            continue
        # single line. candidate W1
        w1 = w - 2 * padh(fs)
        node_exact = (w == nw)
        if w1 <= 0:
            continue
        slopes[p.get("text") or ""].append(
            (fs, w1, scr, p.get("id"), "node_hug" if node_exact else "pad"))
        fits["node_hug" if node_exact else "pad"] += 1

print("width sources: %s" % dict(fits))
print()
multi = {t: v for t, v in slopes.items() if len(set(f for f, *_ in v)) > 1
         or len(v) > 1}
for t, v in sorted(multi.items()):
    v = sorted(v)
    sps = [w1 / f for f, w1, *_ in v]
    span = (max(sps) - min(sps)) / (max(sps) + min(sps)) / 2
    tag = "STABLE" if span < 0.06 else "SCATTER %2.1f%%" % (span * 100)
    print("%-30r fs=%-14s slopes=%-28s %s"
          % (t[:30],
             ", ".join("%.0f" % f for f, *_ in v)[:14],
             (", ".join("%.3f" % s for s in sps[:6]))[:28],
             tag), )
