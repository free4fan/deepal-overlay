package com.walter.overlay;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.text.TextUtils;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class InlineOverlayManager {
    private final Context context;
    private final WindowManager windowManager;
    private final Map<String, TextView> activeViews = new HashMap<>();
    private int statusBarHeight = 0;

    public InlineOverlayManager(Context context) {
        this.context = context;
        this.windowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
        int resourceId = context.getResources().getIdentifier("status_bar_height", "dimen", "android");
        if (resourceId > 0) statusBarHeight = context.getResources().getDimensionPixelSize(resourceId);
    }

    public void clearAll() {
        for (TextView v : activeViews.values()) {
            try { windowManager.removeViewImmediate(v); } catch (Exception ignored) {}
        }
        activeViews.clear();
    }

    public void showTranslation(int left, int top, int width, int height,
                                 String translatedText, float origTextSize, int bgColor,
                                 boolean wordWrap, boolean darkOverlay) {
        if (translatedText == null || translatedText.isEmpty()) return;

        DisplayMetrics dm = context.getResources().getDisplayMetrics();
        int screenWidth = dm.widthPixels;

        // Key by position — same text at different positions gets separate overlays
        String key = left + "," + top;

        float textSize = Math.max(10, Math.min(origTextSize, 24));
        float density = dm.density;

        // Smart line break: max ~13 chars per line (only if word wrap enabled)
        String displayText = wordWrap ? wrapText(translatedText, 13) : translatedText;
        int lineCount = displayText.split("\n").length;
        boolean multiline = lineCount > 1;

        // Calculate width based on longest line
        int longestLine = 0;
        for (String line : displayText.split("\n")) {
            longestLine = Math.max(longestLine, line.length());
        }
        float charWidth = textSize * density * 0.6f;
        int textWidth = (int)(longestLine * charWidth) + 24;
        int overlayWidth = Math.max(width, Math.min(textWidth, (int)(screenWidth * 0.9)));
        if (left + overlayWidth > screenWidth) {
            overlayWidth = screenWidth - left - 10;
        }

        // Update existing overlay at this position
        TextView existing = activeViews.get(key);
        if (existing != null) {
            String currentText = existing.getText().toString();
            if (!currentText.equals(displayText)) {
                existing.setText(displayText);
            }
            WindowManager.LayoutParams lp = (WindowManager.LayoutParams) existing.getLayoutParams();
            int newHeight = multiline ? WindowManager.LayoutParams.WRAP_CONTENT : Math.max(height, 20);
            if (lp.x != left || lp.y != top || lp.width != overlayWidth || lp.height != newHeight) {
                lp.x = left;
                lp.y = top;
                lp.width = overlayWidth;
                lp.height = newHeight;
                try { windowManager.updateViewLayout(existing, lp); } catch (Exception ignored) {}
            }
            return;
        }

        // Create new overlay — matches native app appearance
        TextView tv = new TextView(context);
        tv.setText(displayText);
        int textColor;
        if (darkOverlay) {
            bgColor = 0xDD1A1A1A;
            textColor = 0xFFFFFFFF;
        } else {
            textColor = isLightColor(bgColor) ? 0xFF333333 : 0xFFFFFFFF;
        }
        tv.setTextColor(textColor);
        tv.setBackgroundColor(bgColor);
        tv.setTypeface(Typeface.DEFAULT);
        tv.setIncludeFontPadding(false);

        if (multiline) {
            tv.setSingleLine(false);
            tv.setMaxLines(4);
            tv.setEllipsize(TextUtils.TruncateAt.END);
            tv.setGravity(Gravity.TOP | Gravity.START);
        } else {
            tv.setSingleLine(true);
            tv.setEllipsize(TextUtils.TruncateAt.END);
            tv.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        }

        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, textSize);

        int padH = Math.max(2, width / 30);
        int padV = Math.max(1, height / 10);
        tv.setPadding(padH, padV, padH, padV);

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;

        int overlayHeight = multiline
            ? WindowManager.LayoutParams.WRAP_CONTENT
            : Math.max(height + padV * 2, 20);

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            overlayWidth + padH * 2,
            overlayHeight,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE |
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            android.graphics.PixelFormat.OPAQUE);

        params.x = left;
        params.y = top;
        params.gravity = Gravity.TOP | Gravity.START;

        try {
            windowManager.addView(tv, params);
            activeViews.put(key, tv);
        } catch (Exception e) {
            // ignore
        }
    }

    public void removeNotIn(Set<String> currentPositions) {
        List<String> toRemove = new ArrayList<>();
        for (String key : activeViews.keySet()) {
            if (!currentPositions.contains(key)) {
                toRemove.add(key);
            }
        }
        for (String key : toRemove) {
            TextView v = activeViews.remove(key);
            if (v != null) {
                try { windowManager.removeViewImmediate(v); } catch (Exception ignored) {}
            }
        }
    }

    private boolean isLightColor(int color) {
        int r = (color >> 16) & 0xFF;
        int g = (color >> 8) & 0xFF;
        int b = color & 0xFF;
        double luminance = (0.299 * r + 0.587 * g + 0.114 * b);
        return luminance > 128;
    }

    private String wrapText(String text, int maxChars) {
        if (text == null || text.length() <= maxChars) return text;

        StringBuilder result = new StringBuilder();
        String remaining = text;

        while (remaining.length() > maxChars) {
            // Look for last space before maxChars
            int breakAt = remaining.lastIndexOf(' ', maxChars);
            if (breakAt <= 0) {
                // No space found — force break at maxChars
                breakAt = maxChars;
            }
            result.append(remaining, 0, breakAt).append("\n");
            remaining = remaining.substring(breakAt).trim();
        }
        result.append(remaining);
        return result.toString();
    }
}
