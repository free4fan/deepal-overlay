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
                                 String translatedText, float origTextSize) {
        if (translatedText == null || translatedText.isEmpty()) return;

        DisplayMetrics dm = context.getResources().getDisplayMetrics();
        int screenWidth = dm.widthPixels;

        // Key by position — same text at different positions gets separate overlays
        String key = left + "," + top;

        float textSize = Math.max(10, Math.min(origTextSize, 24));

        // Calculate width to fully cover original text
        float charWidth = textSize * dm.density * 0.6f;
        int textWidth = (int)(translatedText.length() * charWidth) + 24;
        int overlayWidth = Math.max(width, Math.min(textWidth, (int)(screenWidth * 0.9)));
        if (left + overlayWidth > screenWidth) {
            overlayWidth = screenWidth - left - 10;
        }

        // Update existing overlay at this position
        TextView existing = activeViews.get(key);
        if (existing != null) {
            // Update text if translation changed
            String currentText = existing.getText().toString();
            if (!currentText.equals(translatedText)) {
                existing.setText(translatedText);
            }
            WindowManager.LayoutParams lp = (WindowManager.LayoutParams) existing.getLayoutParams();
            if (lp.x != left || lp.y != top || lp.width != overlayWidth || lp.height != Math.max(height, 20)) {
                lp.x = left;
                lp.y = top;
                lp.width = overlayWidth;
                lp.height = Math.max(height, 20);
                try { windowManager.updateViewLayout(existing, lp); } catch (Exception ignored) {}
            }
            return;
        }

        // Create new overlay — matches native app appearance
        TextView tv = new TextView(context);
        tv.setText(translatedText);
        tv.setTextColor(0xFF333333);   // dark text, like native app
        tv.setBackgroundColor(Color.WHITE);  // solid white, covers original
        tv.setTypeface(Typeface.DEFAULT);    // regular weight, not bold
        tv.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        tv.setSingleLine(true);
        tv.setEllipsize(TextUtils.TruncateAt.END);
        tv.setIncludeFontPadding(false);

        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, textSize);

        // Minimal padding — match native text view feel
        int padH = Math.max(2, width / 30);
        int padV = Math.max(0, height / 10);
        tv.setPadding(padH, padV, padH, padV);

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            overlayWidth,
            Math.max(height, 20),
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
