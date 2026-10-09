#!/usr/bin/env python3
"""Fix the adaptive-wrap pass (first implementation had:
 1) accepting the loop-exit fs without a fitsWrapped confirmation,
 2) wrap box = min(column, node box) — too narrow for 2-line wraps,
 3) line budget < 2 for dense nodes (pill may grow downward),
 4) fixed 2-line height instead of the actual line count,
 5) wrap gate tied to 0.9x source font instead of a readability target.
"""
import sys

F = '/home/user/projects/deepal-overlay/app/src/main/java/com/walter/overlay/InlineOverlayManager.java'
src = open(F, encoding='utf-8').read()


def rep_once(src, old, new, label):
    n = src.count(old)
    assert n == 1, f'[{label}] found {n} occurrences'
    print(f'[{label}] ok')
    return src.replace(old, new)


# ---- A) constants ----
old = (
    '    // A single line that would need a font smaller than this is unreadable —\n'
    '    // wrap the translation to two lines at the source font instead (the CJK\n'
    "    // glyph is ~1em, so source font ≈ what the app itself renders there)\n"
    '    private static final int WRAP_MIN_SP = 12;\n'
)
new = (
    '    // Wrapped captions below this font are no better than the proportional\n'
    '    // one-line shrink — stop stepping the wrap size down here.\n'
    '    private static final float WRAP_FLOOR_SP = FIT_MIN_SP;\n'
    '    // Below this one-line font size the caption reads as "squeezed": try a\n'
    '    // 2-3 line wrap at a readable font instead. CJK glyph ≈ 1em, so the\n'
    '    // source font ≈ what fits in the Chinese box.\n'
    '    private static final float WRAP_DESIRED_SP = 12;\n'
)
src = rep_once(src, old, new, 'A-constants')

# ---- B) fit pass ----
i = src.find('        // Fit the available width (fitW: the column limit / field).')
j = src.find('        int width;\n')
assert i >= 0 and j > i, 'B anchors'
new_fit = (
    '        // Fit the available width (fitW: the column limit / field).\n'
    '        // A one-liner that would need a font below the readability target\n'
    '        // becomes a wrapped caption: the CJK glyph is ~1em, so the source\n'
    '        '
    '        font is about what fits in the field, and the caption wraps to\n'
    '        // 2-3 lines inside the COLUMN (the node box alone is often too\n'
    '        // narrow for a readable wrap; the next column starts further).\n'
    '        boolean multiline = wordWrap && textPxWidth + padH * 2 > fitW;\n'
    '        int wrapLines = 0; // 0 = no wrap chosen\n'
    '        if (!multiline && textPxWidth + padH * 2 > fitW) {\n'
    '            // Largest one-line font that fits fitW: width(fs) = t*fs + 0.8fs\n'
    '            // (t = text width per base-font px, 0.8 = 2*padH per px).\n'
    '            float t = textPxWidth / textSizePx;\n'
    '            float fs1 = fitW / (t + 0.8f);\n'
    '            float desiredPx = WRAP_DESIRED_SP * dm.density;\n'
    '            float floorPx = WRAP_FLOOR_SP * dm.density;\n'
    '            if (fs1 < desiredPx || fs1 < textSizePx * 0.9f) {\n'
    '                // The one-liner wants a too-small font: try wrapping at the\n'
    '                // largest readable size. Box = the column (fitW); height is\n'
    '                // limited by the box, the pill may grow below the node.\n'
    '                int budget = lineBudget(spec.height, textSizePx);\n'
    '                float fs = textSizePx;\n'
    '                while (fs >= floorPx &&\n'
    '                        (wrapLines = wrapLineCount(spec.text, fitW, fs, budget)) == 0) {\n'
    '                    fs -= 1f;\n'
    '                }\n'
    '                if (wrapLines > 0) {\n'
    '                    // Readable wrap found at fs: apply it.\n'
    '                    textSizePx = fs;\n'
    '                    padH = Math.max(4, (int) (textSizePx * 0.4f));\n'
    '                    padV = Math.max(2, (int) (textSizePx * 0.3f));\n'
    '                    measurePaint.setTextSize(textSizePx);\n'
    '                    textPxWidth = measurePaint.measureText(spec.text);\n'
    '                    multiline = true;\n'
    '                } else if (fs1 >= floorPx) {\n'
    '                    // No readable wrap (single unbreakable word / tight box):\n'
    '                    // the largest readable one-line font.\n'
    '                    textSizePx = fs1;\n'
    '                    padH = Math.max(4, (int) (textSizePx * 0.4f));\n'
    '                    padV = Math.max(2, (int) (textSizePx * 0.3f));\n'
    '                    if (standaloneRow) textCap = (int) (est * 1.4f) + padH * 2;\n'
    '                    measurePaint.setTextSize(textSizePx);\n'
    '                    textPxWidth = measurePaint.measureText(spec.text);\n'
    '                } else {\n'
    '                    // Below even the floor one-lined: shrink to FIT_MIN_SP;\n'
    '                    // ellipsize remains the last resort.\n'
    '                    float scale = (fitW - padH * 2) / textPxWidth;\n'
    '                    textSizePx = Math.max(floorPx, textSizePx * scale);\n'
    '                    padH = Math.max(4, (int) (textSizePx * 0.4f));\n'
    '                    padV = Math.max(2, (int) (textSizePx * 0.3f));\n'
    '                    if (standaloneRow) textCap = (int) (est * 1.4f) + padH * 2;\n'
    '                    measurePaint.setTextSize(textSizePx);\n'
    '                    textPxWidth = measurePaint.measureText(spec.text);\n'
    '                }\n'
    '            } else {\n'
    '                // Mild overflow: keep one line, fit it in the field\n'
    '                // (a small shrink below the CJK font is acceptable).\n'
    '                textSizePx = fs1;\n'
    '                padH = Math.max(4, (int) (textSizePx * 0.4f));\n'
    '                padV = Math.max(2, (int) (textSizePx * 0.3f));\n'
    '                if (standaloneRow) textCap = (int) (est * 1.4f) + padH * 2;\n'
    '                measurePaint.setTextSize(textSizePx);\n'
    '                textPxWidth = measurePaint.measureText(spec.text);\n'
    '            }\n'
    '        }\n'
)
# drop the leading broken line artifact from a previous generation
new_fit = new_fit.replace("        '        font is about", "        '        font is about", 1)
print(f'[B-fit] {j - i} chars')
src = src[:i] + new_fit + src[j:]

# ---- C) height: multiline from actual line count ----
old = (
    '        int height;\n'
    '        if (multiline) {\n'
    '            int lh = (int) (textSizePx * 1.25f);\n'
    '            if (tallIconBox) {\n'
    '                // Icon card: compact 2-line caption, at least the box tall.\n'
    '                height = (int) Math.max(spec.height, 2f * lh + padV * 2f);\n'
    '            } else if (spec.height <= textSizePx * 2.2f) {\n'
    '                // Dense list row: short caption, at least the box tall.\n'
    '                height = Math.max(spec.height, (int) (2f * lh + padV * 2f));\n'
    '            } else {\n'
    '                // Loose CJK box: cover the box itself (the wrap\n'
    '                // simulation already kept the font inside it).\n'
    '                height = spec.height;\n'
    '            }\n'
    '        } else {\n'
)
new = (
    '        int height;\n'
    '        if (multiline) {\n'
    '            int lh = (int) (textSizePx * 1.25f);\n'
    '            int lines = wrapLines > 0 ? wrapLines : 2;\n'
    '            if (wordWrap && wrapLines == 0) {\n'
    '                // User word-wrap mode: the TextView breaks on its own.\n'
    '                height = WindowManager.LayoutParams.WRAP_CONTENT;\n'
    '            } else {\n'
    '                height = lines * lh + padV * 2;\n'
    '                if (tallIconBox || spec.height > textSizePx * 2.2f) {\n'
    '                    // Loose/icon box: cover the CJK itself as well.\n'
    '                    height = Math.max(height, spec.height);\n'
    '                }\n'
    '            }\n'
    '        } else {\n'
)
src = rep_once(src, old, new, 'C-height')

# ---- D) helpers: fitsWrapped -> wrapLineCount (int) + new lineBudget ----
i = src.find('    // How many caption lines the box can hold')
j = src.find('    private void applyBackground')
assert i >= 0 and j > i, 'D anchors'
k = src.rfind('\n', i, j)
new_helpers = (
    '    // How many caption lines the box allows (pill may grow below the\n'
    '    '
    '    node, so at least 2; capped at 3 — a 4+ line slab is never right).\n'
    '    private int lineBudget(int boxHeightPx, float textSizePx) {\n'
    '        if (boxHeightPx <= 0) return 2;\n'
    '        int padV = Math.max(2, (int) (textSizePx * 0.3f));\n'
    '        int lh = (int) (textSizePx * 1.25f);\n'
    '        if (lh <= 0) return 2;\n'
    '        int n = (boxHeightPx - padV * 2) / lh + 1;\n'
    '        return Math.max(2, Math.min(3, n));\n'
    '    }\n'
    '\n'
    '    // Greedy word-wrap simulation matching TextView: breaks happen on\n'
    '    // spaces; a word wider than the box is NOT broken (it would clip),\n'
    '    // so that size is infeasible. Returns the wrapped line count (1-3),\n'
    '    // or 0 when the text cannot fit inside boxWidthPx at fsPx within the\n'
    '    // line budget or the box height.\n'
    '    private int wrapLineCount(String text, float boxWidthPx, float fsPx,\n'
    '                              int maxLines) {\n'
    '        measurePaint.setTextSize(fsPx);\n'
    '        int padH = Math.max(4, (int) (fsPx * 0.4f));\n'
    '        int padV = Math.max(2, (int) (fsPx * 0.3f));\n'
    '        float avail = boxWidthPx - 2f * padH;\n'
    '        if (avail < fsPx) return 0; // not even one glyph fits\n'
    '        int lines = 1;\n'
    '        float x = 0;\n'
    '        for (String word : text.split(" ", -1)) {\n'
    '            float ww = measurePaint.measureText(word);\n'
    '            float need = (x > 0 ? measurePaint.measureText(" ") : 0) + ww;\n'
    '            if (x + need > avail && x > 0) {\n'
    '                x = ww;\n'
    '                lines++;\n'
    '                if (lines > maxLines) return 0;\n'
    '            } else {\n'
    '                x += need;\n'
    '            }\n'
    '            if (x > avail) return 0; // unbreakable word: this size is unusable\n'
    '        }\n'
    '        return lines;\n'
    '    }\n'
)
print(f'[D-helpers] {k + 1 - i} chars')
src = src[:i] + new_helpers + src[k + 1:]

# ---- E) debug log: add the wrap decision ----
old = ('            + " fontPx=" + (int) textSizePx + " hidden=" + hidden\n'
       '            + " -> " + width + "x"\n')
new = ('            + " fontPx=" + (int) textSizePx + " wrapL=" + wrapLines\n'
       '            + " hidden=" + hidden + " -> " + width + "x"\n')
src = rep_once(src, old, new, 'E-log')

for token in ['WRAP_MIN_SP', 'fitsWrapped']:
    n = src.count(token)
    if n:
        sys.exit(f'leftover {token} x{n}')
open(F, 'w', encoding='utf-8').write(src)
print('OK: wrap-fix complete')
