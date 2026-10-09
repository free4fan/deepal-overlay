#!/usr/bin/env python3
# One-shot refactor of InlineOverlayManager.computeLayout:
#  - drops the stackedBox branch (false positive on icon cards)
#  - adds tallIconBox (icon+subtitle tiles: one-line pill hugging the box)
#  - adaptive fit: readable 2-line wrap instead of shrinking below 12sp
# Re-runnable: fails loudly if the anchors are no longer present.
import sys

F = '/home/user/projects/deepal-overlay/app/src/main/java/com/walter/overlay/InlineOverlayManager.java'
src = open(F, encoding='utf-8').read()


def rep_between(src, start_a, end_a, new_block, label, keep_end=True):
    i = src.find(start_a)
    if i < 0:
        sys.exit('[' + label + '] start not found: ' + start_a[:60])
    j = src.find(end_a, i)
    if j < 0:
        sys.exit('[' + label + '] end not found: ' + end_a[:60])
    end = j if keep_end else j + len(end_a)
    seg = src[i:end]
    if '    private ' in seg or '    public ' in seg:
        sys.exit('[' + label + '] crosses method boundary')
    print('[' + label + '] ' + str(len(seg)) + ' chars')
    return src[:i] + new_block + src[end:]


R1 = '\n'.join([
    '        // Fit the available width (fitW: the column limit / field).',
    '        // A one-liner that would need a font below the readability floor',
    "        // (or far below the box's own CJK font) becomes a",
    '        // wrapped caption instead of an unreadable sliver: the CJK glyph',
    '        // is ~1em, so the source font is about what fits in the field, and',
    '        // the caption wraps inside it. The wrap box is the field width',
    '        // (node box / wideRow cap), never wider than the column.',
    '        boolean multiline = wordWrap && textPxWidth + padH * 2 > fitW;',
    '        if (!multiline && textPxWidth + padH * 2 > fitW) {',
    '            // Largest one-line font that fits fitW: width(fs) = t*fs + 0.8fs',
    '            // (t = text width per base-font px, 0.8 = 2*padH per px).',
    '            float t = textPxWidth / textSizePx;',
    '            float fs1 = fitW / (t + 0.8f);',
    '            float floorPx = WRAP_MIN_SP * dm.density;',
    '            if (fs1 < floorPx || fs1 < textSizePx * 0.9f) {',
    '                // A single line needs a too-small font: try wrapping.',
    '                float wrapW = Math.min(fitW, spec.width);',
    '                if (wideRow) wrapW = Math.min(wrapW, est * 2.2f);',
    '                int budget = lineBudget(spec.height, textSizePx);',
    '                float fs = textSizePx;',
    '                while (fs > floorPx && !fitsWrapped(spec.text, wrapW, fs, budget,',
    '                        spec.height, dm.density)) {',
    '                    fs -= 1f;',
    '                }',
    '                if (fs >= floorPx - 0.5f) {',
    '                    // Readable wrap found at fs: apply it.',
    '                    textSizePx = fs;',
    '                    padH = Math.max(4, (int) (textSizePx * 0.4f));',
    '                    padV = Math.max(2, (int) (textSizePx * 0.3f));',
    '                    measurePaint.setTextSize(textSizePx);',
    '                    textPxWidth = measurePaint.measureText(spec.text);',
    '                    multiline = true;',
    '                    if (fitW > wrapW) fitW = (int) wrapW;',
    '                } else if (fs1 >= floorPx) {',
    '                    // Wrap does not fit (single long word / tight box):',
    '                    // the largest readable one-line font.',
    '                    textSizePx = fs1;',
    '                    padH = Math.max(4, (int) (textSizePx * 0.4f));',
    '                    padV = Math.max(2, (int) (textSizePx * 0.3f));',
    '                    if (standaloneRow) textCap = (int) (est * 1.4f) + padH * 2;',
    '                    measurePaint.setTextSize(textSizePx);',
    '                    textPxWidth = measurePaint.measureText(spec.text);',
    '                } else {',
    '                    // Below even one readable line: shrink to FIT_MIN_SP;',
    '                    // ellipsize remains the last resort.',
    '                    float floor1 = FIT_MIN_SP * dm.density;',
    '                    float scale = (fitW - padH * 2) / textPxWidth;',
    '                    textSizePx = Math.max(floor1, textSizePx * scale);',
    '                    padH = Math.max(4, (int) (textSizePx * 0.4f));',
    '                    padV = Math.max(2, (int) (textSizePx * 0.3f));',
    '                    if (standaloneRow) textCap = (int) (est * 1.4f) + padH * 2;',
    '                    measurePaint.setTextSize(textSizePx);',
    '                    textPxWidth = measurePaint.measureText(spec.text);',
    '                }',
    '            } else {',
    '                // Mild overflow: keep one line, fit it in the field',
    '                // (a small shrink below the CJK font is acceptable).',
    '                textSizePx = fs1;',
    '                padH = Math.max(4, (int) (textSizePx * 0.4f));',
    '                padV = Math.max(2, (int) (textSizePx * 0.3f));',
    '                if (standaloneRow) textCap = (int) (est * 1.4f) + padH * 2;',
    '                measurePaint.setTextSize(textSizePx);',
    '                textPxWidth = measurePaint.measureText(spec.text);',
    '            }',
    '        }',
]) + '\n'

R2 = '\n'.join([
    '        int width;',
    '        if (multiline) {',
    '            // Icon tiles keep the wrap inside the box; everything else',
    '            // takes the whole field width.',
    '            width = tallIconBox ? (int) Math.min(fitW, spec.width) : fitW;',
    '        } else if (tallIconBox) {',
    '            // Icon-card tile: hug the box width so the CJK inside is',
    '            // covered without spilling to the next column.',
    '            width = (int) Math.min(maxW, spec.width);',
    '        } else {',
    '            int textArea = (int) Math.min(textPxWidth, maxW - padH * 2);',
    '            int nodeArea = (int) Math.min(spec.width, maxW - padH * 2);',
    '            if (standaloneRow) {',
    '                textArea = Math.min(textArea, textCap - padH);',
    '                nodeArea = Math.min(nodeArea, textCap - padH);',
    '            } else if (wideRow) {',
    "                // The source label fills the row's left part, the pill may",
    '                // be wider than the label but must not swallow the row.',
    '                nodeArea = Math.min(nodeArea, (int) (est * 2.2f));',
    '            }',
    '            width = Math.max(nodeArea, textArea) + padH * 2;',
    '        }',
]) + '\n'

R3 = '\n'.join([
    '        int height;',
    '        if (multiline) {',
    '            int lh = (int) (textSizePx * 1.25f);',
    '            if (tallIconBox) {',
    '                // Icon card: compact 2-line caption, at least the box tall.',
    '                height = (int) Math.max(spec.height, 2f * lh + padV * 2f);',
    '            } else if (spec.height <= textSizePx * 2.2f) {',
    '                // Dense list row: short caption, at least the box tall.',
    '                height = Math.max(spec.height, (int) (2f * lh + padV * 2f));',
    '            } else {',
    '                // Loose CJK box: cover the box itself (the wrap',
    '                // simulation already kept the font inside it).',
    '                height = spec.height;',
    '            }',
    '        } else {',
    '            int minH = Math.max((int) (textSizePx + padV * 2), MIN_SINGLE_LINE_HEIGHT);',
    '            int h;',
    '            if (standaloneRow) {',
    '                // The container is several lines tall, the text is one line.',
    '                h = (int) (textSizePx * 1.35f) + padV * 2;',
    '            } else if (tallIconBox) {',
    '                // Icon-card tile: one line, not a box-tall slab (the',
    "                // \"Зарядка\" 184x130 pill).",
    '                h = (int) (textSizePx * 1.4f) + padV * 2;',
    '            } else {',
    '                h = spec.height + padV * 2;',
    '            }',
    '            height = Math.max(h, minH);',
    '        }',
]) + '\n'

R4 = '\n'.join([
    '        int gravity;',
    '        if (tallIconBox) {',
    '            // Icon-card tiles center the CJK under the icon: center the',
    '            // (1-2 line) caption in the box too.',
    '            gravity = Gravity.CENTER;',
    '        } else if (multiline) {',
    '            gravity = spec.centered && !wideRow',
    '                ? Gravity.TOP | Gravity.CENTER_HORIZONTAL',
    '                : Gravity.TOP | Gravity.START;',
    '        } else {',
    '            gravity = spec.centered && !wideRow',
    '                ? Gravity.CENTER',
    '                : Gravity.CENTER_VERTICAL | Gravity.START;',
    '        }',
]) + '\n'

HELPERS = '\n'.join([
    '    // How many caption lines the box can hold: ~1.25 line-height each',
    "    // plus the pill's vertical padding; min 1, max 3 (taller stacks",
    '    // read as a slab; the real boxes here hold at most 2-3 CJK lines).',
    '    private int lineBudget(int boxHeightPx, float textSizePx) {',
    '        if (boxHeightPx <= 0) return 1;',
    '        int padV = Math.max(2, (int) (textSizePx * 0.3f));',
    '        int lh = (int) (textSizePx * 1.25f);',
    '        if (lh <= 0) return 1;',
    '        int n = (boxHeightPx - padV * 2) / lh + 1;',
    '        return Math.max(1, Math.min(3, n));',
    '    }',
    '',
    '    // Greedy word-wrap simulation matching TextView: breaks happen on',
    '    // spaces; a word wider than the box is NOT broken (it would clip),',
    '    // so that size is infeasible. True when the text wraps into at most',
    '    // maxLines lines inside boxWidthPx (minus H padding) at fsPx and the',
    '    // result is no taller than the box.',
    '    private boolean fitsWrapped(String text, float boxWidthPx, float fsPx,',
    '                                int maxLines, int boxHeightPx, float density) {',
    '        measurePaint.setTextSize(fsPx);',
    '        int padH = Math.max(4, (int) (fsPx * 0.4f));',
    '        int padV = Math.max(2, (int) (fsPx * 0.3f));',
    '        float avail = boxWidthPx - 2f * padH;',
    '        if (avail < fsPx) return false; // not even one glyph fits',
    '        int lines = 1;',
    '        float x = 0;',
    '        for (String word : text.split(" ", -1)) {',
    '            float ww = measurePaint.measureText(word);',
    '            float need = (x > 0 ? measurePaint.measureText(" ") : 0) + ww;',
    '            if (x + need > avail && x > 0) {',
    '                x = ww;',
    '                lines++;',
    '                if (lines > maxLines) return false;',
    '            } else {',
    '                x += need;',
    '            }',
    '            if (x > avail) return false; // unbreakable word: size unusable',
    '        }',
    '        float h = lines * fsPx * 1.25f + padV * 2f;',
    '        int boxH = boxHeightPx > 0 ? boxHeightPx : Integer.MAX_VALUE;',
    '        return h <= boxH + 2f;',
    '    }',
]) + '\n'

src = rep_between(src, '        float textPxWidth = measurePaint.measureText(spec.text);\n',
                  '        int width;\n',
                  ('        float textPxWidth = measurePaint.measureText(spec.text);\n\n'
                   + R1), 'R1-fit', keep_end=True)
src = rep_between(src, '        int width;\n',
                  '        int height;\n',
                  R2, 'R2-width', keep_end=True)
src = rep_between(src, '        int height;\n',
                  '        int bgColor =', R3, 'R3-height', keep_end=True)
src = rep_between(src, '        int gravity;\n',
                  '        // A carousel mid-slide', R4, 'R4-gravity', keep_end=True)

old = '            if (spec.centered && !standaloneRow && !wideRow && width >= spec.width) {'
new = ('            if (spec.centered && !standaloneRow && !wideRow && !tallIconBox\n'
       '                    && width >= spec.width) {')
assert src.count(old) == 1, 'R5 anchor count ' + str(src.count(old))
src = src.replace(old, new)
print('[R5-ddx]')

old = '" stB=" + stackedBox'
assert src.count(old) == 1
src = src.replace(old, '" tIB=" + tallIconBox')
print('[R6-log]')

i = src.find('    // Greedy word-wrap simulation')
j = src.find('    private void applyBackground')
assert i >= 0 and j > i, 'R7 anchors'
k = src.rfind('\n', i, j)  # step back to the blank line before the helper
seg = src[i:k + 1]
print('[R7-helpers] ' + str(len(seg)) + ' chars')
src = src[:i] + HELPERS + src[k + 1:]

for token in ['stackedBox', 'stackPx', 'basePx', 'wrappedLineCount']:
    n = src.count(token)
    if n:
        sys.exit('leftover ' + token + ' x' + str(n))
assert src.count('tallIconBox') >= 8, src.count('tallIconBox')
open(F, 'w', encoding='utf-8').write(src)
print('OK: refactor complete')
