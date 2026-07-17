package com.walter.overlay;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.text.TextUtils;
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

    public InlineOverlayManager(Context context) {
        this.context = context;
        this.windowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
    }

    public void clearAll() {
        for (TextView v : activeViews.values()) {
            try { windowManager.removeViewImmediate(v); } catch (Exception ignored) {}
        }
        activeViews.clear();
    }

    public void showTranslation(int left, int top, int width, int height, 
                                 String translatedText, float origTextSize) {
        if (translatedText == null || translatedText.isEmpty()) return;

        TextView existing = activeViews.get(translatedText);
        if (existing != null) {
            // Update position if it moved
            WindowManager.LayoutParams lp = (WindowManager.LayoutParams) existing.getLayoutParams();
            if (lp.x != left || lp.y != top) {
                lp.x = left;
                lp.y = top;
                lp.width = Math.max(width, 40);
                lp.height = Math.max(height, 20);
                try { windowManager.updateViewLayout(existing, lp); } catch (Exception ignored) {}
            }
            return;
        }

        TextView tv = new TextView(context);
        tv.setText(translatedText);
        tv.setTextColor(Color.BLACK);
        tv.setBackgroundColor(Color.WHITE);
        tv.setTypeface(Typeface.DEFAULT);
        tv.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        tv.setSingleLine(true);
        tv.setEllipsize(TextUtils.TruncateAt.END);
        tv.setIncludeFontPadding(false);

        float textSize = Math.max(10, Math.min(origTextSize, 24));
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, textSize);

        int padH = Math.max(2, width / 20);
        int padV = Math.max(0, height / 8);
        tv.setPadding(padH, padV, padH, padV);

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            Math.max(width, 40),
            Math.max(height, 20),
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE |
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            android.graphics.PixelFormat.TRANSLUCENT);

        params.x = left;
        params.y = top;
        params.gravity = Gravity.TOP | Gravity.START;

        try {
            windowManager.addView(tv, params);
            activeViews.put(translatedText, tv);
        } catch (Exception e) {
            // ignore
        }
    }

    public void removeNotIn(Set<String> currentTexts) {
        List<String> toRemove = new ArrayList<>();
        for (String key : activeViews.keySet()) {
            if (!currentTexts.contains(key)) {
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
}
