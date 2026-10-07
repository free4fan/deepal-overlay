package com.walter.overlay;

import android.content.Context;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.text.TextUtils;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
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

        public OverlaySpec(String key, String text, int width, int height,
                           float textSizeSp, boolean darkZone, boolean centered) {
            this.key = key;
            this.text = text;
            this.width = width;
            this.height = height;
            this.textSizeSp = textSizeSp;
            this.darkZone = darkZone;
            this.centered = centered;
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

        Layout(int width, int height, float textSizePx, int bgColor, int textColor,
               boolean multiline, int gravity, int padH, int padV) {
            this.width = width;
            this.height = height;
            this.textSizePx = textSizePx;
            this.bgColor = bgColor;
            this.textColor = textColor;
            this.multiline = multiline;
            this.gravity = gravity;
            this.padH = padH;
            this.padV = padV;
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
        DisplayMetrics dm = context.getResources().getDisplayMetrics();
        int screenH = dm.heightPixels;
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
                                boolean wordWrap, boolean darkOverlay) {
        if (translatedText == null || translatedText.isEmpty()) return;

        String key = left + "," + top;
        OverlaySpec spec = new OverlaySpec(key, translatedText, width, height,
            textSizeSp, darkZone, centered);

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

        WindowManager.LayoutParams lp = (WindowManager.LayoutParams) tv.getLayoutParams();
        if (lp.x != parseX(spec.key) || lp.y != parseY(spec.key)
                || lp.width != layout.width || lp.height != layout.height) {
            lp.x = parseX(spec.key);
            lp.y = parseY(spec.key);
            lp.width = layout.width;
            lp.height = layout.height;
            try { windowManager.updateViewLayout(tv, lp); } catch (Exception ignored) {}
        }
    }

    private TextView create(OverlaySpec spec, boolean wordWrap, boolean darkOverlay,
                            List<OverlaySpec> siblings) {
        Layout layout = computeLayout(spec, wordWrap, darkOverlay, siblings);

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

        params.x = parseX(spec.key);
        params.y = parseY(spec.key);
        params.gravity = Gravity.TOP | Gravity.START;

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
        if (siblings != null) {
            int near = -1;
            for (OverlaySpec s : siblings) {
                if (s == spec) continue;
                int dx = parseX(s.key) - x;
                if (dx > 0 && dx < ROW_NEIGHBOR_MAX
                        && Math.abs(parseY(s.key) - parseY(spec.key)) <= ROW_SAME_ROW_MAX_DY) {
                    if (near < 0 || dx < near) near = dx;
                }
            }
            if (near > 48) maxW = Math.min(maxW, near - ROW_GAP);
        }

        // Font size in absolute px: the user's system font scale must not stretch
        // an overlay out of its fixed window (the old SP setting did exactly that)
        float textSizePx = spec.textSizeSp * dm.density;
        textSizePx = Math.max(MIN_TEXT_SP * dm.density,
            Math.min(textSizePx, MAX_TEXT_SP * dm.density));

        int padH = Math.max(4, (int) (textSizePx * 0.4f));
        int padV = Math.max(2, (int) (textSizePx * 0.3f));
        measurePaint.setTextSize(textSizePx);
        float textPxWidth = measurePaint.measureText(spec.text);

        // Fit the column: shrink the font (down to FIT_MIN_SP) so the full text fits
        // instead of ellipsizing; ellipsize remains the last resort at the floor size
        if (!wordWrap && textPxWidth + padH * 2 > maxW) {
            float floorPx = FIT_MIN_SP * dm.density;
            float scale = floorPx >= textSizePx ? 1f : (maxW - padH * 2) / textPxWidth;
            if (scale < 1f) {
                textSizePx = Math.max(floorPx, textSizePx * scale);
                padH = Math.max(4, (int) (textSizePx * 0.4f));
                padV = Math.max(2, (int) (textSizePx * 0.3f));
                measurePaint.setTextSize(textSizePx);
                textPxWidth = measurePaint.measureText(spec.text);
            }
        }

        // Native wrapping: let the TextView itself break lines when the text does not
        // fit in the available width (the old 13-char manual wrap is gone)
        boolean multiline = wordWrap && textPxWidth + padH * 2 > maxW;

        int width;
        if (multiline) {
            width = maxW;
        } else {
            int textArea = (int) Math.min(textPxWidth, maxW - padH * 2);
            int nodeArea = (int) Math.min(spec.width, maxW - padH * 2);
            width = Math.max(nodeArea, textArea) + padH * 2;
        }

        int height;
        if (multiline) {
            height = WindowManager.LayoutParams.WRAP_CONTENT;
        } else {
            int minH = Math.max((int) (textSizePx + padV * 2), MIN_SINGLE_LINE_HEIGHT);
            height = Math.max(spec.height + padV * 2, minH);
        }

        int bgColor = darkOverlay ? BG_DARK_SETTING
            : spec.darkZone ? BG_DARK_ZONE : BG_SCRIM;
        int textColor = 0xFFFFFFFF;

        int gravity;
        if (multiline) {
            gravity = spec.centered
                ? Gravity.TOP | Gravity.CENTER_HORIZONTAL
                : Gravity.TOP | Gravity.START;
        } else {
            gravity = spec.centered
                ? Gravity.CENTER
                : Gravity.CENTER_VERTICAL | Gravity.START;
        }

        return new Layout(width, height, textSizePx, bgColor, textColor,
            multiline, gravity, padH, padV);
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
