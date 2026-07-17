package com.walter.overlay;

import android.content.Context;
import android.graphics.Color;
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
        setBackgroundColor(0xDD000000);
        setPadding(20, 12, 20, 12);

        textView = new TextView(context);
        textView.setTextSize(15f);
        textView.setTextColor(Color.WHITE);
        textView.setTypeface(Typeface.MONOSPACE);
        textView.setGravity(Gravity.START);
        textView.setMaxLines(8);
        
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
                
                if (fadeScheduler != null) {
                    fadeScheduler.shutdownNow();
                }
                fadeScheduler = Executors.newSingleThreadScheduledExecutor();
                fadeScheduler.schedule(this::hide, 15000, TimeUnit.MILLISECONDS);
            });
        }
    }

    public void setError() {
        if (textView != null) {
            textView.post(() -> {
                textView.setTextColor(Color.RED);
                textView.setText("Translation error");
                show();
            });
        }
    }

    public void show() {
        if (getVisibility() != View.VISIBLE) {
            setVisibility(View.VISIBLE);
        }
    }

    private void hide() {
        textView.post(() -> {
            if (getVisibility() == View.VISIBLE) {
                setVisibility(View.GONE);
            }
        });
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        if (fadeScheduler != null) fadeScheduler.shutdownNow();
    }
}
