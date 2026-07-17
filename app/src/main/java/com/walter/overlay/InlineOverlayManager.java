package com.walter.overlay;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;

public class InlineOverlayManager {
    private final Context context;
    private final WindowManager windowManager;
    private final List<View> activeViews = new ArrayList<>();

    public InlineOverlayManager(Context context) {
        this.context = context;
        this.windowManager = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
    }

    public void clearAll() {
        for (View v : activeViews) {
            try { windowManager.removeViewImmediate(v); } catch (Exception ignored) {}
        }
        activeViews.clear();
    }

    public void showTranslation(int left, int top, int width, int height, 
                                 String translatedText, float origTextSize) {
        if (translatedText == null || translatedText.isEmpty()) return;

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
        int padV = Math.max(1, height / 6);
        tv.setPadding(padH, padV, padH, padV);

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            : WindowManager.LayoutParams.TYPE_PHONE;

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            Math.max(width, 40),
            Math.max(height, 20),
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            android.graphics.PixelFormat.TRANSLUCENT);

        params.x = left;
        params.y = top;
        params.gravity = Gravity.TOP | Gravity.START;

        try {
            windowManager.addView(tv, params);
            activeViews.add(tv);
        } catch (Exception e) {
            // ignore
        }
    }
}
