package com.walter.overlay;

import android.content.Intent;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.*;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.core.view.WindowCompat;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.card.MaterialCardView;

public class MainActivity extends AppCompatActivity {
    private boolean resumed = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        setContentView(R.layout.activity_main);

        MaterialButton accBtn = findViewById(R.id.accBtn);
        MaterialButton applyBtn = findViewById(R.id.applyBtn);
        MaterialButton quitBtn = findViewById(R.id.quitBtn);
        MaterialButton openDeepalBtn = findViewById(R.id.openDeepalBtn);
        MaterialButton testOverlayBtn = findViewById(R.id.testOverlayBtn);
        MaterialCardView actionsCard = findViewById(R.id.actionsCard);
        MaterialSwitch scanAllSwitch = findViewById(R.id.scanAllSwitch);
        MaterialButtonToggleGroup langToggle = findViewById(R.id.langToggle);
        MaterialButton langEn = findViewById(R.id.langEn);
        MaterialButton langRu = findViewById(R.id.langRu);

        android.content.SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);

        // Status icons
        ImageView accIcon = findViewById(R.id.accIcon);
        ImageView overlayIcon = findViewById(R.id.overlayIcon);
        TextView accStatusLabel = findViewById(R.id.accStatusLabel);
        TextView overlayStatusLabel = findViewById(R.id.overlayStatusLabel);

        // Check permissions
        String serviceId = getPackageName() + "/" + TranslationService.class.getName();
        String enabledServices = Settings.Secure.getString(getContentResolver(),
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean isAccEnabled = enabledServices != null && enabledServices.contains(serviceId);
        boolean hasOverlay = checkOverlayPermission();

        // Accessibility status
        if (isAccEnabled) {
            accIcon.setImageResource(android.R.drawable.ic_menu_info_details);
            accIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_success));
            accStatusLabel.setText("Accessibility service active");
            accBtn.setText("Enabled");
            accBtn.setEnabled(false);
            accBtn.setBackgroundTintList(ContextCompat.getColorStateList(this, R.color.status_success));
        } else {
            accIcon.setImageResource(android.R.drawable.ic_dialog_alert);
            accIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_error));
            accStatusLabel.setText("Accessibility service required");
            accBtn.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        }

        // Overlay status
        if (hasOverlay) {
            overlayIcon.setImageResource(android.R.drawable.ic_menu_info_details);
            overlayIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_success));
            overlayStatusLabel.setText("Overlay permission granted");
        } else {
            overlayIcon.setImageResource(android.R.drawable.ic_dialog_alert);
            overlayIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_error));
            overlayStatusLabel.setText("Overlay permission required");

            LinearLayout container = findViewById(R.id.overlayButtonsContainer);
            MaterialButton grantBtn = new MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
            grantBtn.setText("Grant overlay permission");
            grantBtn.setOnClickListener(v -> {
                try {
                    startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
                } catch (Exception e) {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())));
                }
            });
            container.addView(grantBtn);

            MaterialButton confirmBtn = new MaterialButton(this);
            confirmBtn.setText("Permission granted — continue");
            confirmBtn.setOnClickListener(v -> {
                prefs.edit().putBoolean("overlay_manual_granted", true).apply();
                recreate();
            });
            container.addView(confirmBtn);
        }

        // Actions card — only show when permissions OK
        if (isAccEnabled && hasOverlay) {
            actionsCard.setVisibility(android.view.View.VISIBLE);

            openDeepalBtn.setOnClickListener(v -> {
                try {
                    Intent launch = getPackageManager().getLaunchIntentForPackage("deepal.com.cn.app");
                    if (launch != null) {
                        startActivity(launch);
                    } else {
                        Intent intent = new Intent();
                        intent.setClassName("deepal.com.cn.app", "deepal.com.cn.app.SplashActivity");
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(intent);
                    }
                } catch (Exception e) {
                    Toast.makeText(this, "Deepal app not found", Toast.LENGTH_SHORT).show();
                }
            });

            testOverlayBtn.setOnClickListener(v -> {
                try {
                    WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
                    TextView testView = new TextView(this);
                    testView.setText(" Overlay works! ");
                    testView.setTextSize(22f);
                    testView.setBackgroundColor(0xDD000000);
                    testView.setTextColor(0xFF00FF00);
                    testView.setPadding(32, 24, 32, 24);
                    WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                        WindowManager.LayoutParams.WRAP_CONTENT,
                        WindowManager.LayoutParams.WRAP_CONTENT,
                        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                        PixelFormat.TRANSLUCENT);
                    params.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
                    params.y = 100;
                    wm.addView(testView, params);
                    testView.postDelayed(() -> {
                        try { wm.removeView(testView); } catch (Exception ignored) {}
                    }, 3000);
                } catch (Exception e) {
                    Toast.makeText(this, "Error: " + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            });
        } else {
            actionsCard.setVisibility(android.view.View.GONE);
        }

        // Settings
        if (prefs.getInt("target_lang", 0) == 0) {
            langToggle.check(R.id.langEn);
        } else {
            langToggle.check(R.id.langRu);
        }

        scanAllSwitch.setChecked(prefs.getBoolean("scan_all", true));

        applyBtn.setOnClickListener(v -> {
            int langPos = langToggle.getCheckedButtonId() == R.id.langRu ? 1 : 0;
            prefs.edit()
                .putInt("target_lang", langPos)
                .putBoolean("scan_all", scanAllSwitch.isChecked())
                .apply();
            Toast.makeText(this, "Settings applied", Toast.LENGTH_SHORT).show();
            stopService(new Intent(this, TranslationService.class));
            startService(new Intent(this, TranslationService.class));
        });

        quitBtn.setOnClickListener(v -> {
            prefs.edit().putBoolean("translation_enabled", false).apply();
            stopService(new Intent(this, TranslationService.class));
            finishAffinity();
            System.exit(0);
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (resumed) recreate();
        resumed = true;
    }

    private boolean checkOverlayPermission() {
        if (Settings.canDrawOverlays(this)) return true;
        return getSharedPreferences("deepal", MODE_PRIVATE)
            .getBoolean("overlay_manual_granted", false);
    }
}
