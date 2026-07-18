package com.walter.overlay;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

public class OverlayView extends LinearLayout {
    private TextView textView;
    private final Runnable hideRunnable = this::hide;
    private boolean hidePosted = false;

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

        setVisibility(View.GONE);
    }

    public void setText(String text) {
        if (textView != null) {
            textView.post(() -> {
                textView.setText(text);
                show();
                cancelScheduledHide();
                scheduleHide();
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

    private void scheduleHide() {
        if (!hidePosted) {
            hidePosted = true;
            textView.postDelayed(hideRunnable, 15000);
        }
    }

    private void cancelScheduledHide() {
        if (hidePosted) {
            hidePosted = false;
            textView.removeCallbacks(hideRunnable);
        }
    }

    private void hide() {
        hidePosted = false;
        if (getVisibility() == View.VISIBLE) {
            setVisibility(View.GONE);
        }
    }
}
