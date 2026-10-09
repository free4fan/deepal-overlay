#!/usr/bin/env python3
"""Vertical clearance for wrapped captions: a pill may grow below its node
only into the empty gap until the next node (75% of it). Without this,
«Цифровой ключ» in a 152x61 card wrapped to 292x124 and covered the
Bluetooth card below. Adds maxPillH, threads it through the wrap pass and
the height blocks, and makes wrapLineCount check the resulting height.
"""
import sys

F = '/home/user/projects/deepal-overlay/app/src/main/java/com/walter/overlay/InlineOverlayManager.java'
src = open(F, encoding='utf-8').read()


def rep_once(old, new, label):
    global src
    n = src.count(old)
    assert n == 1, f'[{label}] found {n} occurrences'
    print(f'[{label}] ok')
    src = src.replace(old, new)


# ---- A) sibling loop: also measure the gap to the nearest node below ----
old = (
    '        boolean closeRow = false;\n'
    '        if (siblings != null) {\n'
    '            int near = -1;\n'
    '            for (OverlaySpec s : siblings) {\n'
    '                if (s == spec) continue;\n'
    '                int dx = parseX(s.key) - x;\n'
    '                if (dx > 0 && dx < ROW_NEIGHBOR_MAX\n'
    '                        && Math.abs(parseY(s.key) - parseY(spec.key)) <= ROW_SAME_ROW_MAX_DY) {\n'
    '                    closeRow = true;\n'
    '                    if (near < 0 || dx < near) near = dx;\n'
    '                }\n'
    '            }\n'
    '            if (near > 48) maxW = Math.min(maxW, near - ROW_GAP);\n'
    '        }\n'
)
new = (
    '        boolean closeRow = false;\n'
    '        int gapBelow = -1; // empty strip under the node, until the next node\n'
    '        if (siblings != null) {\n'
    '            int near = -1;\n'
    '            int y = parseY(spec.key);\n'
    '            int bottom = y + spec.height;\n'
    '            for (OverlaySpec s : siblings) {\n'
    '                if (s == spec) continue;\n'
    '                int dx = parseX(s.key) - x;\n'
    '                if (dx > 0 && dx < ROW_NEIGHBOR_MAX\n'
    '                        && Math.abs(parseY(s.key) - y) <= ROW_SAME_ROW_MAX_DY) {\n'
    '                    closeRow = true;\n'
    '                    if (near < 0 || dx < near) near = dx;\n'
    '                }\n'
    '                // The nearest node below that overlaps the pill column\n'
    '                // bounds how far a wrapped caption may stretch down.\n'
    '                int dy = parseY(s.key) - y;\n'
    '                if (dy > 0 && dy < 600 && parseX(s.key) < x + maxW\n'
    '                        && parseX(s.key) + s.width > x) {\n'
    '                    int g = parseY(s.key) - bottom;\n'
    '                    if (gapBelow < 0 || g < gapBelow) gapBelow = g;\n'
    '                }\n'
    '            }\n'
    '            if (near > 48) maxW = Math.min(maxW, near - ROW_GAP);\n'
    '        }\n'
    '        // A caption may grow below the node into at most 75% of that gap;\n'
    '        // with no node below (list bottom, nav band) it is unlimited.\n'
    '        int maxPillH = gapBelow >= 0\n'
    '            ? spec.height + (int) (Math.max(0, gapBelow) * 0.75f)\n'
    '            : Integer.MAX_VALUE;\n'
)
rep_once(old, new, 'A-gap')

# ---- B) wrap loop: pass the height limit ----
old = (
    '                int budget = lineBudget(spec.height, textSizePx);\n'
    '                float fs = textSizePx;\n'
    '                while (fs >= floorPx &&\n'
    '                        (wrapLines = wrapLineCount(spec.text, fitW, fs, budget)) == 0) {\n'
    '                    fs -= 1f;\n'
    '                }\n'
)
new = (
    '                int budget = lineBudget(spec.height, textSizePx);\n'
    '                float fs = textSizePx;\n'
    '                while (fs >= floorPx &&\n'
    '                        (wrapLines = wrapLineCount(spec.text, fitW, fs, budget,\n'
    '                                                   maxPillH)) == 0) {\n'
    '                    fs -= 1f;\n'
    '                }\n'
)
rep_once(old, new, 'B-loop')

# ---- C) height blocks: cap by maxPillH ----
old = (
    '            } else {\n'
    '                height = lines * lh + padV * 2;\n'
    '                if (tallIconBox || spec.height > textSizePx * 2.2f) {\n'
    '                    // Loose/icon box: cover the CJK itself as well.\n'
    '                    height = Math.max(height, spec.height);\n'
    '                }\n'
    '            }\n'
)
new = (
    '            } else {\n'
    '                height = lines * lh + padV * 2;\n'
    '                if (tallIconBox || spec.height > textSizePx * 2.2f) {\n'
    '                    // Loose/icon box: cover the CJK itself as well.\n'
    '                    height = Math.max(height, spec.height);\n'
    '                }\n'
    '                height = Math.min(height, maxPillH);\n'
    '            }\n'
)
rep_once(old, new, 'C-height-mline')

old = (
    '            height = Math.max(h, minH);\n'
    '        }\n'
)
new = (
    '            height = Math.max(h, minH);\n'
    '            height = Math.min(height, maxPillH);\n'
    '        }\n'
)
rep_once(old, new, 'D-height-single')

# ---- E) wrapLineCount: signature + height check ----
old = (
    '    // line budget or the box height.\n'
    '    private int wrapLineCount(String text, float boxWidthPx, float fsPx,\n'
    '                              int maxLines) {\n'
)
new = (
    '    // line budget, or the resulting block taller than maxHpx.\n'
    '    private int wrapLineCount(String text, float boxWidthPx, float fsPx,\n'
    '                              int maxLines, int maxHpx) {\n'
)
rep_once(old, new, 'E1-signature')

old = (
    '            if (x > avail) return 0; // unbreakable word: this size is unusable\n'
    '        }\n'
    '        return lines;\n'
    '    }\n'
)
new = (
    '            if (x > avail) return 0; // unbreakable word: this size is unusable\n'
    '        }\n'
    '        float h = lines * fsPx * 1.25f + 2f * Math.max(2, (int) (fsPx * 0.3f));\n'
    '        if (h > maxHpx + 2f) return 0; // would run into the node below\n'
    '        return lines;\n'
    '    }\n'
)
rep_once(old, new, 'E2-heightcheck')

# ---- F) log: show the clearance cap ----
old = '            + " | maxW=" + maxW + " fitW=" + fitW + " textPx=" + (int) textPxWidth\n'
new = ('            + " | maxW=" + maxW + " fitW=" + fitW\n'
       '            + " cap=" + (maxPillH < Integer.MAX_VALUE ? maxPillH : -9)\n'
       '            + " textPx=" + (int) textPxWidth\n')
rep_once(old, new, 'F-log')

open(F, 'w', encoding='utf-8').write(src)
print('OK: clearance applied')
