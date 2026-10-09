package com.walter.overlay;

import android.content.Context;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.text.TextUtils;
import android.util.DisplayMetrics;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class InlineOverlayManager {
    // Reuse an overlay (move it) instead of recreate when the same text moved by at most this much
    private static final int DRIFT_TOLERANCE = 240;
    // Unclaimed overlays survive this long (covers ~2 scan cycles): during fast
    // scrolling the accessibility tree is often read incomplete — without grace,
    // a sparse scan wipes all overlays and they only return after the scroll ends
    private static final long UNCLAIMED_GRACE_MS = 700;

    private static final int MIN_TEXT_SP = 10;
    private static final int MAX_TEXT_SP = 24;
    private static final int SCREEN_EDGE_MARGIN = 8;
    private static final int WRAP_MAX_LINES = 8;
    private static final int CORNER_RADIUS_DP = 6;
    private static final int MIN_SINGLE_LINE_HEIGHT = 20;

    private static final int BG_DARK_SETTING = 0xDD1A1A1A; // manual "Dark overlay" mode
    private static final int BG_DARK_ZONE = 0xFF202020;    // toolbar/header: opaque dark, blends into the bar
    private static final int BG_SCRIM = 0xFF1A1A1A;        // content: opaque dark — original CJK must never show through
    // A pill may not cross this absolute-x boundary (nearest right neighbor's left edge minus this gap)
    private static final int ROW_GAP = 6;
    // Siblings farther apart than this are unrelated, not a row neighbor
    private static final int ROW_NEIGHBOR_MAX = 600;
    // Vertical offset that still counts as "same row". Real rows align within a
    // few px (top/bottom-aligned or centered of similar heights); dense lists put
    // the next row 55px+ further down. The old 140 band treated a node from the
    // adjacent row as a row neighbor and clamped this pill to their gap — a 60px
    // "Це…" instead of "Центр сообщений".
    private static final int ROW_SAME_ROW_MAX_DY = 50;
    // Font may shrink to this (sp) so the text fits the column instead of ellipsizing
    private static final float FIT_MIN_SP = 9;
    // A pill narrower than this whose text still overflows is a meaningless
    // one-letter "А…" sliver — hide it (width 0) instead of drawing it
    private static final int MIN_MEANINGFUL_PILL = 72;
    // Wrapped captions below this font are no better than the proportional
    // one-line shrink — stop stepping the wrap size down here.
    private static final float WRAP_FLOOR_SP = FIT_MIN_SP;
    // Below this one-line font size the caption reads as "squeezed": try a
    // 2-3 line wrap at a readable font instead. CJK glyph ≈ 1em, so the
    // source font ≈ what fits in the Chinese box.
    private static final float WRAP_DESIRED_SP = 12;

    private final Context context;
    private final WindowManager windowManager;
    private final Map<String, TextView> activeViews = new HashMap<>();
    private final Map<TextView, Long> lastSeenMs = new HashMap<>();
    private final Map<TextView, Integer> bgColors = new HashMap<>();
    private final Paint measurePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private int cornerRadiusPx = -1;

    public static class OverlaySpec {
        public final String key;
        public final String text;
        public final int width;
        public final int height;
        public final float textSizeSp;
        public final boolean darkZone;
        public final boolean centered;
        // Estimated width of the source CJK text in px (one Han char ≈ 1em).
        // 0 = unknown / not estimated — layout falls back to the node width.
        // Needed because a11y nodes report row-container bounds (e.g. a section
        // header 704px wide with a 4-char title in its left part): the pill
        // must cover the text, not the whole container.
        public final int estSourceWidthPx;

        public OverlaySpec(String key, String text, int width, int height,
                           float textSizeSp, boolean darkZone, boolean centered,
                           int estSourceWidthPx) {
            this.key = key;
            this.text = text;
            this.width = width;
            this.height = height;
            this.textSizeSp = textSizeSp;
            this.darkZone = darkZone;
            this.centered = centered;
            this.estSourceWidthPx = estSourceWidthPx;
        }
    }

    private static final class Layout {
        final int width;
        final int height;
        final float textSizePx;
        final int bgColor;
        final int textColor;
        final boolean multiline;
        final int gravity;
        final int padH;
        final int padV;
        final boolean hidden;
        // Offset (in px) from the node's top-left where the window is anchored.
        // Single-line pills are centered on the node: the source CJK sits
        // centered in the node box, so a top-left-anchored window padded by
        // padV/padH shifts the translation diagonally off the CJK center
        // (perceivable as the caption being displaced from the original).
        // Multiline wraps grow downward and stay top-anchored.
        final int dx;
        final int dy;

        Layout(int width, int height, float textSizePx, int bgColor, int textColor,
               boolean multiline, int gravity, int padH, int padV, boolean hidden,
               int dx, int dy) {
            this.width = width;
            this.height = height;
            this.textSizePx = textSizePx;
            this.bgColor = bgColor;
            this.textColor = textColor;
            this.multiline = multiline;
            this.gravity = gravity;
            this.padH = padH;
            this.padV = padV;
            this.hidden = hidden;
            this.dx = dx;
            this.dy = dy;
        }
    }

    public InlineOverlayManager(Context context) {
        this.context = context;
        this.windowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
    }

    public void clearAll() {
        for (TextView v : activeViews.values()) {
            try { windowManager.removeViewImmediate(v); } catch (Exception ignored) {}
        }
        activeViews.clear();
        lastSeenMs.clear();
        bgColors.clear();
    }

    /**
     * Diff-based update: existing overlays are reused and moved in-place
     * (no remove/recreate), so scrolling does not cause flicker.
     */
    public void reconcile(List<OverlaySpec> specs, boolean wordWrap, boolean darkOverlay) {
        Set<TextView> claimed = new HashSet<>();
        long now = android.os.SystemClock.uptimeMillis();

        // Pass 1: exact position match — update in place
        for (OverlaySpec s : specs) {
            TextView tv = activeViews.get(s.key);
            if (tv != null) {
                apply(tv, s, wordWrap, darkOverlay, specs);
                claimed.add(tv);
            }
        }

        // Pass 2: position drift — reuse overlay with same text within tolerance
        for (OverlaySpec s : specs) {
            if (activeViews.containsKey(s.key)) continue;
            TextView best = null;
            String bestKey = null;
            int bestDist = Integer.MAX_VALUE;
            for (Map.Entry<String, TextView> e : activeViews.entrySet()) {
                TextView tv = e.getValue();
                if (claimed.contains(tv)) continue;
                if (!s.text.equals(tv.getTag())) continue;
                int d = drift(e.getKey(), s.key);
                if (d <= DRIFT_TOLERANCE && d < bestDist) {
                    best = tv;
                    bestKey = e.getKey();
                    bestDist = d;
                }
            }
            if (best != null) {
                activeViews.remove(bestKey);
                apply(best, s, wordWrap, darkOverlay, specs);
                activeViews.put(s.key, best);
                claimed.add(best);
            }
        }

        // Pass 3: remove overlays that no longer match any node.
        // Unclaimed overlays get a grace period before removal — a sparse scan
        // mid-fling must not wipe the screen. Fully offscreen views go at once.
        // Use the *real* display height (resource context reports window
        // metrics, which understates the space where nodes like the bottom
        // nav bar actually live).
        int screenH = realDisplayHeight();
        for (Iterator<Map.Entry<String, TextView>> it = activeViews.entrySet().iterator(); it.hasNext();) {
            Map.Entry<String, TextView> e = it.next();
            TextView tv = e.getValue();
            if (claimed.contains(tv)) {
                lastSeenMs.put(tv, now);
                continue;
            }
            Long seen = lastSeenMs.get(tv);
            boolean withinGrace = seen != null && (now - seen) < UNCLAIMED_GRACE_MS;
            WindowManager.LayoutParams lp = (WindowManager.LayoutParams) tv.getLayoutParams();
            boolean offscreen = lp.y + lp.height < -50 || lp.y > screenH + 50;
            if (withinGrace && !offscreen) continue;
            it.remove();
            lastSeenMs.remove(tv);
            bgColors.remove(tv);
            try { windowManager.removeViewImmediate(tv); } catch (Exception ignored) {}
        }

        // Pass 4: create overlays for new nodes
        for (OverlaySpec s : specs) {
            if (!activeViews.containsKey(s.key)) {
                TextView tv = create(s, wordWrap, darkOverlay, specs);
                if (tv != null) {
                    activeViews.put(s.key, tv);
                    lastSeenMs.put(tv, now);
                }
            }
        }
    }

    public void showTranslation(int left, int top, int width, int height,
                                String translatedText, float textSizeSp,
                                boolean darkZone, boolean centered,
                                int estSourceWidthPx,
                                boolean wordWrap, boolean darkOverlay) {
        if (translatedText == null || translatedText.isEmpty()) return;

        String key = left + "," + top;
        OverlaySpec spec = new OverlaySpec(key, translatedText, width, height,
            textSizeSp, darkZone, centered, estSourceWidthPx);

        TextView existing = activeViews.get(key);
        if (existing != null) {
            apply(existing, spec, wordWrap, darkOverlay, null);
        } else {
            existing = create(spec, wordWrap, darkOverlay, null);
            if (existing == null) return;
            activeViews.put(key, existing);
        }
        lastSeenMs.put(existing, android.os.SystemClock.uptimeMillis());
    }

    private void apply(TextView tv, OverlaySpec spec, boolean wordWrap, boolean darkOverlay,
                       List<OverlaySpec> siblings) {
        Layout layout = computeLayout(spec, wordWrap, darkOverlay, siblings);
        if (layout.hidden) {
            // Slide sliver: park the existing overlay (it is claimed by this
            // spec, so reconciliation keeps tracking — it reappears as soon as
            // the node settles and the pill becomes wide again).
            WindowManager.LayoutParams lp0 = (WindowManager.LayoutParams) tv.getLayoutParams();
            if (lp0.width != 0) {
                updateParams(tv, lp0, 0, 0,
                    parseX(spec.key) + layout.dx, parseY(spec.key) + layout.dy);
            }
            if (tv.getVisibility() != View.GONE) tv.setVisibility(View.GONE);
            return;
        }
        if (tv.getVisibility() != View.VISIBLE) tv.setVisibility(View.VISIBLE);

        // Tag holds the raw text — used for drift matching in reconcile()
        if (!spec.text.contentEquals(tv.getText())) {
            tv.setText(spec.text);
        }
        if (!spec.text.equals(tv.getTag())) {
            tv.setTag(spec.text);
        }
        tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, layout.textSizePx);
        tv.setTextColor(layout.textColor);
        applyBackground(tv, layout.bgColor);
        tv.setSingleLine(!layout.multiline);
        tv.setMaxLines(layout.multiline ? WRAP_MAX_LINES : 1);
        tv.setEllipsize(TextUtils.TruncateAt.END);
        tv.setGravity(layout.gravity);
        tv.setPadding(layout.padH, layout.padV, layout.padH, layout.padV);

        updateParams(tv, (WindowManager.LayoutParams) tv.getLayoutParams(),
            layout.width, layout.height,
            parseX(spec.key) + layout.dx, parseY(spec.key) + layout.dy);
    }

    // Only touches the window when something actually changed
    private void updateParams(TextView tv, WindowManager.LayoutParams lp,
                              int width, int height, int x, int y) {
        if (lp.width == width && lp.height == height && lp.x == x && lp.y == y) return;
        lp.width = width;
        lp.height = height;
        lp.x = x;
        lp.y = y;
        try { windowManager.updateViewLayout(tv, lp); } catch (Exception ignored) {}
    }

    private TextView create(OverlaySpec spec, boolean wordWrap, boolean darkOverlay,
                            List<OverlaySpec> siblings) {
        Layout layout = computeLayout(spec, wordWrap, darkOverlay, siblings);
        if (layout.hidden) return null; // don't spawn a slide sliver

        TextView tv = new TextView(context);
        tv.setText(spec.text);
        tv.setTag(spec.text);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, layout.textSizePx);
        tv.setTextColor(layout.textColor);
        applyBackground(tv, layout.bgColor);
        tv.setTypeface(Typeface.DEFAULT);
        tv.setIncludeFontPadding(false);
        tv.setSingleLine(!layout.multiline);
        if (layout.multiline) tv.setMaxLines(WRAP_MAX_LINES);
        tv.setEllipsize(TextUtils.TruncateAt.END);
        tv.setGravity(layout.gravity);
        tv.setPadding(layout.padH, layout.padV, layout.padH, layout.padV);

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            layout.width,
            layout.height,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE |
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            android.graphics.PixelFormat.TRANSLUCENT);

        params.x = parseX(spec.key) + layout.dx;
        params.y = parseY(spec.key) + layout.dy;
        params.gravity = Gravity.TOP | Gravity.START;
        // On this device WMS rewrites overlay params (adds CENTER to the
        // gravity, forces alpha 0.8) — the CJK then shows *through* the pill
        // and reads as the translation being misaligned/offset from the
        // original text. Force full opacity; the rounded corners are
        // per-pixel alpha inside the surface and are not affected.
        params.alpha = 1.0f;

        try {
            windowManager.addView(tv, params);
            return tv;
        } catch (Exception e) {
            bgColors.remove(tv);
            return null;
        }
    }

    private Layout computeLayout(OverlaySpec spec, boolean wordWrap, boolean darkOverlay,
                                 List<OverlaySpec> siblings) {
        DisplayMetrics dm = context.getResources().getDisplayMetrics();
        int screenWidth = dm.widthPixels;
        int x = parseX(spec.key);

        // Column limit: a pill must not cover a row neighbor's column (a 4-icon grid
        // leaves ~column width of room, not the whole screen to the right)
        int maxW = Math.max(48, screenWidth - x - SCREEN_EDGE_MARGIN);
        boolean closeRow = false;
        int gapBelow = -1; // empty strip under the node, until the next node
        int leftClear = x; // empty space to the node's left (screen edge default);
        // a left row neighbor shrinks it — the pill must not cover that column
        if (siblings != null) {
            int near = -1;
            int y = parseY(spec.key);
            int bottom = y + spec.height;
            for (OverlaySpec s : siblings) {
                if (s == spec) continue;
                int dx = parseX(s.key) - x;
                if (dx > 0 && dx < ROW_NEIGHBOR_MAX
                        && Math.abs(parseY(s.key) - y) <= ROW_SAME_ROW_MAX_DY) {
                    closeRow = true;
                    if (near < 0 || dx < near) near = dx;
                } else if (dx < 0 && dx > -ROW_NEIGHBOR_MAX
                        && Math.abs(parseY(s.key) - y) <= ROW_SAME_ROW_MAX_DY) {
                    leftClear = Math.max(0, Math.min(leftClear, x - (parseX(s.key) + s.width)));
                }
                // The nearest node below that overlaps the pill column
                // bounds how far a wrapped caption may stretch down.
                int dy = parseY(s.key) - y;
                if (dy > 0 && dy < 600 && parseX(s.key) < x + maxW
                        && parseX(s.key) + s.width > x) {
                    int g = parseY(s.key) - bottom;
                    if (gapBelow < 0 || g < gapBelow) gapBelow = g;
                }
            }
            if (near > 48) maxW = Math.min(maxW, near - ROW_GAP);
        }
        // A caption may grow below the node into at most 75% of that gap;
        // with no node below (list bottom, nav band) it is unlimited.
        int maxPillH = gapBelow >= 0
            ? spec.height + (int) (Math.max(0, gapBelow) * 0.75f)
            : Integer.MAX_VALUE;

        // Font in absolute px (clamped to the 10..24sp reading range)
        float textSizePx = spec.textSizeSp * dm.density;
        textSizePx = Math.max(MIN_TEXT_SP * dm.density,
            Math.min(textSizePx, MAX_TEXT_SP * dm.density));
        float basePx = textSizePx;

        int padH = Math.max(4, (int) (textSizePx * 0.4f));
        int padV = Math.max(2, (int) (textSizePx * 0.3f));
        int est = spec.estSourceWidthPx;

        // Three node shapes, all with the source text well smaller than the node:
        //
        // B) tall header container — the a11y bounds are a 2+ line row box
        //    (e.g. a 704x108 node whose 4-char title sits in its left part).
        //    Pill: capped to ~1.4x the source extent, one text line tall.
        boolean standaloneRow = !closeRow && est > 0
            && spec.width > est * 2.5f && spec.height > textSizePx * 1.8f;
        //
        // T) tall icon-card box — a near-square tile whose box is several font
        //    lines tall but whose text is short (e.g. 184x130 for 充电服务,
        //    常用服务; the car's 车锁/车窗 grid cells). The source CJK sits in
        //    part of the box; the pill hugs the box width (the next column
        //    starts far enough away) and is one line tall, centered on the box.
        boolean tallIconBox = !closeRow && !standaloneRow && est > 0
            && spec.width <= est * 1.35f + 2
            && spec.height > textSizePx * 1.6f && spec.height < textSizePx * 6f;
        //
        // A) wide single-line row — a settings row / header line (e.g. 720x60
        //    for a 4-char label, or 878x45 for "保养提醒"). The source text
        //    fills the left part, the translation may legitimately be wider:
        //    cap the node contribution to ~2.2x the source extent (never the
        //    whole row), keep the font at the source size when it fits.
        boolean wideRow = !closeRow && !standaloneRow && !tallIconBox && est > 0
            && spec.width > est * 2.5f;

        int textCap = 0;
        int fitW = maxW;
        // Heading floor for standalone row titles: a section header (车辆设置,
        // 960×123 CJK box) must read like a heading (≥ 16sp), not be squeezed
        // below the CJK font (it came out 13sp + "…"). WRAP_DESIRED_SP + 4sp.
        // The cap grows to one line at 16sp ONLY when the column allows —
        // otherwise the normal fit/wrap path keeps the est*1.4 cap.
        float headingFloorPx = (WRAP_DESIRED_SP + 4f) * dm.density;
        boolean headingCap = false; // cap extended beyond est*1.4 — keep it
        if (standaloneRow) {
            // ~1.4x the source extent: room for a longer translation, not a row
            textCap = (int) (est * 1.4f) + padH * 2;
            fitW = Math.min(maxW, textCap);
            // If one line at the heading floor fits the column, grow the cap
            // to it: the title stays one line at heading size, no ellipsis.
            // Beyond the column the normal fit/wrap path takes over.
            measurePaint.setTextSize(headingFloorPx);
            int atHeading = (int) Math.ceil(measurePaint.measureText(spec.text)
                + headingFloorPx * 0.8f);
            if (atHeading > textCap && atHeading <= maxW) {
                textCap = atHeading;
                fitW = atHeading;
                headingCap = true;
            }
        }

        // Icon-card tiles: the a11y font of a 1-line CJK block can be wider
        // than the tight box (常用服务 4×54px in a 184px tile). Cap the
        // caption font so `est` (the CJK extent at the source font) still
        // spans the box on one line — never below the floor.
        if (tallIconBox && est > 0) {
            float fsTib = basePx * (spec.width - 16f) / est;
            if (fsTib < textSizePx && fsTib >= FIT_MIN_SP * dm.density) {
                textSizePx = fsTib;
                padH = Math.max(4, (int) (textSizePx * 0.4f));
                padV = Math.max(2, (int) (textSizePx * 0.3f));
            }
        }

        measurePaint.setTextSize(textSizePx);
        float textPxWidth = measurePaint.measureText(spec.text);

        // Fit the available width (fitW: the column limit / field).
        // A one-liner that would need a font below the readability target
        // becomes a wrapped caption: the CJK glyph is ~1em, so the source
        // font is about what fits in the field, and the caption wraps to
        // 2-3 lines inside the COLUMN (the node box alone is often too
        // narrow for a readable wrap; the next column starts further).
        boolean multiline = wordWrap && textPxWidth + padH * 2 > fitW;
        int wrapLines = 0; // 0 = no wrap chosen
        float fs1 = -1f;
        if (!multiline && textPxWidth + padH * 2 > fitW) {
            // Largest one-line font that fits fitW: width(fs) = t*fs + 0.8fs
            // (t = text width per base-font px, 0.8 = 2*padH per px).
            float t = textPxWidth / textSizePx;
            fs1 = fitW / (t + 0.8f);
            float desiredPx = WRAP_DESIRED_SP * dm.density;
            float floorPx = WRAP_FLOOR_SP * dm.density;
            if (fs1 < desiredPx) {
                // The one-liner wants a font below the readability target:
                // largest readable size. Box = the column (fitW); height is
                // limited by the box, the pill may grow below the node.
                // The pill may grow into the clearance below (maxPillH), so
                // budget the lines from that at the candidate size (a smaller
                // font fits more lines — a fixed base-font budget undercounts).
                float fs = textSizePx;
                while (fs >= floorPx &&
                        (wrapLines = wrapLineCount(spec.text, fitW, fs,
                                lineBudget(maxPillH, fs), maxPillH)) == 0) {
                    fs -= 1f;
                }
                if (wrapLines > 0) {
                    // Readable wrap found at fs: apply it.
                    textSizePx = fs;
                    padH = Math.max(4, (int) (textSizePx * 0.4f));
                    padV = Math.max(2, (int) (textSizePx * 0.3f));
                    measurePaint.setTextSize(textSizePx);
                    textPxWidth = measurePaint.measureText(spec.text);
                    multiline = true;
                } else if (fs1 >= floorPx) {
                    // No readable wrap (single unbreakable word / tight box):
                    // the largest readable one-line font.
                    textSizePx = fs1;
                    padH = Math.max(4, (int) (textSizePx * 0.4f));
                    padV = Math.max(2, (int) (textSizePx * 0.3f));
                    if (standaloneRow && !headingCap) textCap = (int) (est * 1.4f) + padH * 2;
                    measurePaint.setTextSize(textSizePx);
                    textPxWidth = measurePaint.measureText(spec.text);
                } else {
                    // Below even the floor one-lined: shrink to FIT_MIN_SP;
                    // ellipsize remains the last resort.
                    float scale = (fitW - padH * 2) / textPxWidth;
                    textSizePx = Math.max(floorPx, textSizePx * scale);
                    padH = Math.max(4, (int) (textSizePx * 0.4f));
                    padV = Math.max(2, (int) (textSizePx * 0.3f));
                    if (standaloneRow && !headingCap) textCap = (int) (est * 1.4f) + padH * 2;
                    measurePaint.setTextSize(textSizePx);
                    textPxWidth = measurePaint.measureText(spec.text);
                }
            } else {
                // Mild overflow: keep one line, fit it in the field
                // (a small shrink below the CJK font is acceptable).
                textSizePx = fs1;
                padH = Math.max(4, (int) (textSizePx * 0.4f));
                padV = Math.max(2, (int) (textSizePx * 0.3f));
                if (standaloneRow && !headingCap) textCap = (int) (est * 1.4f) + padH * 2;
                measurePaint.setTextSize(textSizePx);
                textPxWidth = measurePaint.measureText(spec.text);
            }
        }
        // The pad model (0.4em) is a hair optimistic for Cyrillic: guarantee
        // the one-liner truly fits the pill interior (kills micro-ellipses).
        // Never below the wrap floor — a hopeless one-liner ellipsizes instead
        // of becoming an unreadable sliver.
        if (!multiline && textPxWidth > fitW - padH * 2f && fitW >= 48) {
            float clamped = textSizePx * (fitW - padH * 2f - 1f) / textPxWidth;
            if (clamped >= WRAP_FLOOR_SP * dm.density) {
                textSizePx = clamped;
                padH = Math.max(4, (int) (textSizePx * 0.4f));
                padV = Math.max(2, (int) (textSizePx * 0.3f));
                measurePaint.setTextSize(textSizePx);
                textPxWidth = measurePaint.measureText(spec.text);
            }
        }
        int width;
        if (multiline) {
            // Icon tiles keep the wrap inside the box; everything else
            // takes the whole field width.
            width = tallIconBox ? (int) Math.min(fitW, spec.width) : fitW;
        } else if (tallIconBox) {
            // One-line caption on the icon-card tile: hug the box (covers
            // the CJK), growing right only if the translation is longer.
            width = Math.min(maxW,
                Math.max(spec.width, (int) (textPxWidth + padH * 2f)));
        } else {
            int textArea = (int) Math.min(textPxWidth, maxW - padH * 2);
            int nodeArea = (int) Math.min(spec.width, maxW - padH * 2);
            if (standaloneRow) {
                textArea = Math.min(textArea, textCap - padH);
                nodeArea = Math.min(nodeArea, textCap - padH);
            } else if (wideRow) {
                // The source label fills the row's left part, the pill may
                // be wider than the label but must not swallow the row.
                nodeArea = Math.min(nodeArea, (int) (est * 2.2f));
            }
            width = Math.max(nodeArea, textArea) + padH * 2;
        }
        int height;
        if (multiline) {
            int lh = (int) (textSizePx * 1.25f);
            int lines = wrapLines > 0 ? wrapLines : 2;
            if (wordWrap && wrapLines == 0) {
                // User word-wrap mode: the TextView breaks on its own.
                height = WindowManager.LayoutParams.WRAP_CONTENT;
            } else {
                height = lines * lh + padV * 2;
                if (tallIconBox || spec.height > textSizePx * 2.2f) {
                    // Loose/icon box: cover the CJK itself as well.
                    height = Math.max(height, spec.height);
                }
                height = Math.min(height, maxPillH);
            }
        } else {
            int minH = Math.max((int) (textSizePx + padV * 2), MIN_SINGLE_LINE_HEIGHT);
            int h;
            if (standaloneRow) {
                // The container is several lines tall, the text is one line.
                h = (int) (textSizePx * 1.35f) + padV * 2;
            } else if (tallIconBox) {
                // Icon-card tile: one line, not a box-tall slab (the
                // "Зарядка" 184x130 pill).
                h = (int) (textSizePx * 1.4f) + padV * 2;
            } else {
                h = spec.height + padV * 2;
            }
            height = Math.max(h, minH);
            height = Math.min(height, maxPillH);
        }

        int bgColor = darkOverlay ? BG_DARK_SETTING
            : spec.darkZone ? BG_DARK_ZONE : BG_SCRIM;
        int textColor = 0xFFFFFFFF;

        int gravity;
        if (tallIconBox) {
            // Icon-card tiles center the CJK under the icon: center the
            // (1-2 line) caption in the box too.
            gravity = Gravity.CENTER;
        } else if (multiline) {
            gravity = spec.centered && !wideRow
                ? Gravity.TOP | Gravity.CENTER_HORIZONTAL
                : Gravity.TOP | Gravity.START;
        } else {
            gravity = spec.centered && !wideRow
                ? Gravity.CENTER
                : Gravity.CENTER_VERTICAL | Gravity.START;
        }
        // A carousel mid-slide leaves a node partially in: the widest the pill
        // may grow is the gap to the next node (~40px), so only a single
        // letter plus ellipsis fits ("А…"). Draw nothing while it stays in a
        // sliver — the text is unknown here — and restore the pill as soon as
        // the card settles (layout becomes wide enough again).
        boolean hidden = !multiline && width > 0 && width < MIN_MEANINGFUL_PILL
            && textPxWidth + padH * 2 > width;

        // Center the single-line window on the node (see Layout.dx/dy).
        // Source CJK is centered in the node box, and the window is padded
        // around the caption (h = node + 2*padV, w = node + 2*padH when the
        // translation is short), so anchoring at the node top-left pushes the
        // caption down-right off the CJK center — the pill looked displaced.
        // Delta = (node - window) / 2: usually negative (window is slightly
        // larger than the node), so it starts above/left of the node.
        // Bottom nav band: center the single-line pill on the tab's ICON.
        // The a11y node can be the text TextView (width ≈ est) or a wider
        // container; the CJK block is always `est` wide from the node's left
        // edge, and the icon sits above its center (user: the tab pills
        // « Машина »/« Магазин » looked shifted right of the icons — the pill
        // anchored at the CJK's left edge, while RU is 2-3x wider than the
        // block). Center on x + est/2 when the overhang fits the clearances.
        int ddx = 0, ddy = 0;
        if (!multiline) {
            ddy = (spec.height - height) / 2;
            if (parseY(spec.key) > realDisplayHeight() - 130
                    && est > 0 && width > est
                    && !standaloneRow && !tallIconBox) {
                int overhang = (width - est) / 2;
                if (overhang <= leftClear) {
                    ddx = (est - width) / 2;
                    ddx = Math.max(ddx, -x); // never cross the screen edge
                    if (x + ddx + width > x + maxW) ddx = (int) (maxW - width);
                }
            }
        }

        return new Layout(width, height, textSizePx, bgColor, textColor,
            multiline, gravity, padH, padV, hidden, ddx, ddy);
    }

    // How many caption lines the box allows (pill may grow below the
    // node, so at least 2; capped at 3 — a 4+ line slab is never right).
    private int lineBudget(int boxHeightPx, float textSizePx) {
        if (boxHeightPx <= 0) return 2;
        int padV = Math.max(2, (int) (textSizePx * 0.3f));
        int lh = (int) (textSizePx * 1.25f);
        if (lh <= 0) return 2;
        int n = (boxHeightPx - padV * 2) / lh + 1;
        return Math.max(2, Math.min(3, n));
    }

    // Greedy word-wrap simulation matching TextView: breaks happen on
    // spaces; a word wider than the box is NOT broken (it would clip),
    // so that size is infeasible. Returns the wrapped line count (1-3),
    // or 0 when the text cannot fit inside boxWidthPx at fsPx within the
    // line budget, or the resulting block taller than maxHpx.
    private int wrapLineCount(String text, float boxWidthPx, float fsPx,
                              int maxLines, int maxHpx) {
        measurePaint.setTextSize(fsPx);
        int padH = Math.max(4, (int) (fsPx * 0.4f));
        int padV = Math.max(2, (int) (fsPx * 0.3f));
        float avail = boxWidthPx - 2f * padH;
        if (avail < fsPx) return 0; // not even one glyph fits
        // Words break on spaces; an explicit hyphen is also a break point
        // (UAX#14: break after "-", the hyphen stays on the first line —
        // "Concierge-сервис" → 2 readable lines instead of one 10sp sliver).
        // The hyphenated pieces are pre-split so each stays with its tail.
        final java.util.List<String> words = new java.util.ArrayList<>();
        for (String part : text.split(" ", -1)) {
            if (part.length() > 1 && part.indexOf('-') >= 0) {
                int from = 0;
                int h;
                while ((h = part.indexOf('-', from)) >= 0) {
                    words.add(part.substring(from, h + 1));
                    from = h + 1;
                }
                if (from < part.length()) words.add(part.substring(from));
            } else {
                words.add(part);
            }
        }
        int lines = 1;
        float x = 0;
        for (String word : words) {
            float ww = measurePaint.measureText(word);
            float need = (x > 0 ? measurePaint.measureText(" ") : 0) + ww;
            if (x + need > avail && x > 0) {
                x = ww;
                lines++;
                if (lines > maxLines) return 0;
            } else {
                x += need;
            }
            if (x > avail) return 0; // unbreakable word: this size is unusable
        }
        float h = lines * fsPx * 1.25f + 2f * Math.max(2, (int) (fsPx * 0.3f));
        if (h > maxHpx + 2f) return 0; // would run into the node below
        return lines;
    }

    private void applyBackground(TextView tv, int color) {
        Integer current = bgColors.get(tv);
        if (current != null && current == color) return;
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color);
        bg.setCornerRadius(cornerRadiusPx());
        tv.setBackground(bg);
        bgColors.put(tv, color);
    }

    private int cornerRadiusPx() {
        if (cornerRadiusPx < 0) {
            float density = context.getResources().getDisplayMetrics().density;
            cornerRadiusPx = (int) (CORNER_RADIUS_DP * density + 0.5f);
        }
        return cornerRadiusPx;
    }

    // Resource context returns window metrics (system bars subtracted); the
    // real display is taller — node bounds use the full-display space
    private int realDisplayHeight() {
        try {
            android.hardware.display.DisplayManager dm =
                (android.hardware.display.DisplayManager)
                    context.getSystemService(Context.DISPLAY_SERVICE);
            if (dm != null) {
                android.view.Display disp =
                    dm.getDisplay(android.view.Display.DEFAULT_DISPLAY);
                if (disp != null) {
                    DisplayMetrics m = new DisplayMetrics();
                    disp.getRealMetrics(m);
                    return m.heightPixels;
                }
            }
        } catch (Throwable ignored) {
        }
        return context.getResources().getDisplayMetrics().heightPixels;
    }

    private static int parseX(String key) {
        return Integer.parseInt(key.substring(0, key.indexOf(',')));
    }

    private static int parseY(String key) {
        return Integer.parseInt(key.substring(key.indexOf(',') + 1));
    }

    private static int drift(String keyA, String keyB) {
        int dx = parseX(keyA) - parseX(keyB);
        int dy = parseY(keyA) - parseY(keyB);
        return Math.abs(dx) + Math.abs(dy);
    }
}
