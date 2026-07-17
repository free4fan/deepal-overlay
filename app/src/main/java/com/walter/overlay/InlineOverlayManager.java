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
import java.util.HashMap;
import java.util.Map;

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

    private String makeKey(int left, int top, int w, int h) {
        return left + "," + top + "," + w + "," + h;
    }

    public void showTranslation(int left, int top, int width, int height, 
                                 String translatedText, float origTextSize) {
        if (translatedText == null || translatedText.isEmpty()) return;

        String key = makeKey(left, top, width, height);

        // If already showing same text at same position, skip
        TextView existing = activeViews.get(key);
        if (existing != null) {
            CharSequence cur = existing.getText();
            if (cur != null && cur.toString().equals(translatedText)) {
                return; // no change
            }
            // Update text in-place (no remove/add)
            existing.setText(translatedText);
            return;
        }

        // Remove any old view that overlaps significantly
        for (Map.Entry<String, TextView> entry : new HashMap<>(activeViews).entrySet()) {
            String[] parts = entry.getKey().split(",");
            int oldL = Integer.parseInt(parts[0]);
            int oldT = Integer.parseInt(parts[1]);
            int oldW = Integer.parseInt(parts[2]);
            int oldH = Integer.parseInt(parts[3]);
            // Check overlap
            if (left < oldL + oldW && left + width > oldL && top < oldT + oldH && top + height > oldT) {
                try { windowManager.removeViewImmediate(entry.getValue()); } catch (Exception ignored) {}
                activeViews.remove(entry.getKey());
            }
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
            activeViews.put(key, tv);
        } catch (Exception e) {
            // ignore
        }
    }

    public void removeStale(int screenW, int screenH) {
        for (Map.Entry<String, TextView> entry : new HashMap<>(activeViews).entrySet()) {
            String[] parts = entry.getKey().split(",");
            int top = Integer.parseInt(parts[1]);
            // Remove if way off screen
            if (top > screenH + 200 || top < -200) {
                try { windowManager.removeViewImmediate(entry.getValue()); } catch (Exception ignored) {}
                activeViews.remove(entry.getKey());
            }
        }
    }
}
