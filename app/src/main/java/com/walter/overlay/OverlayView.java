package com.walter.overlay;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class OverlayView extends LinearLayout {
    private static final String TAG = "OverlayView";
    private TextView textView;
    private ScheduledExecutorService fadeScheduler;

    public OverlayView(Context context) {
        super(context);
        init(context);
    }

    private void init(Context context) {
        setOrientation(LinearLayout.VERTICAL);
        setBackgroundResource(android.R.drawable.toast_frame);
        
        // Создаём полупрозрачный фон вручную
        setPadding(16, 8, 16, 8);

        textView = new TextView(context);
        textView.setTextSize(14f);
        textView.setTextColor(Color.WHITE);
        textView.setTypeface(Typeface.MONOSPACE);
        textView.setGravity(Gravity.CENTER);
        
        addView(textView, new LayoutParams(
            LayoutParams.MATCH_PARENT,
            LayoutParams.WRAP_CONTENT));

        hide();
    }

    public void setText(String text) {
        if (textView != null) {
            textView.post(() -> {
                textView.setText(text);
                show();
                
                // Сбросить таймер затухания
                if (fadeScheduler != null) {
                    fadeScheduler.shutdownNow();
                }
                fadeScheduler = Executors.newSingleThreadScheduledExecutor();
                fadeScheduler.schedule(this::hide, 8000, TimeUnit.MILLISECONDS);
            });
        }
    }

    public void setError() {
        if (textView != null) {
            textView.post(() -> {
                textView.setTextColor(Color.YELLOW);
                textView.setText("⚠ Ошибка перевода");
                show();
            });
        }
    }

    public void show() {
        if (getVisibility() != View.VISIBLE) {
            setVisibility(View.VISIBLE);
            Log.d(TAG, "Overlay visible");
        }
    }

    private void hide() {
        textView.post(() -> {
            if (getVisibility() == View.VISIBLE) {
                setVisibility(View.GONE);
                Log.d(TAG, "Overlay hidden");
            }
        });
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        if (fadeScheduler != null) fadeScheduler.shutdownNow();
    }
}
