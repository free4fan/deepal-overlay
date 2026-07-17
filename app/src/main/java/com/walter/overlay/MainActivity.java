package com.walter.overlay;

import android.content.Intent;
import android.graphics.PixelFormat;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {
    private boolean resumed = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUI();
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

    private void buildUI() {
        android.content.SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 48, 32, 32);

        // Title + version
        TextView title = new TextView(this);
        title.setText("Deepal Translate v" + BuildConfig.VERSION_NAME);
        title.setTextSize(24f);
        title.setPadding(0, 0, 0, 16);
        root.addView(title);

        // === Permissions section ===
        String serviceId = getPackageName() + "/" + TranslationService.class.getName();
        String enabledServices = Settings.Secure.getString(getContentResolver(),
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean isAccEnabled = enabledServices != null && enabledServices.contains(serviceId);
        boolean hasOverlay = checkOverlayPermission();

        // Accessibility
        TextView accLabel = new TextView(this);
        accLabel.setText(isAccEnabled ? "✅ Accessibility service ON" : "⛔ Accessibility service OFF");
        accLabel.setTextSize(15f);
        accLabel.setPadding(0, 8, 0, 4);
        root.addView(accLabel);

        Button accBtn = new Button(this);
        if (!isAccEnabled) {
            accBtn.setText("Enable Accessibility");
            accBtn.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        } else {
            accBtn.setText("Accessibility OK");
            accBtn.setEnabled(false);
            accBtn.setBackgroundColor(0xFF4CAF50);
            accBtn.setTextColor(0xFFFFFFFF);
        }
        root.addView(accBtn);

        // Overlay
        TextView overlayLabel = new TextView(this);
        overlayLabel.setText(hasOverlay ? "✅ Overlay permission OK" : "⛔ Overlay permission NOT granted");
        overlayLabel.setTextSize(15f);
        overlayLabel.setPadding(0, 12, 0, 4);
        root.addView(overlayLabel);

        if (!hasOverlay) {
            Button overlayBtn = new Button(this);
            overlayBtn.setText("1. Grant overlay permission");
            overlayBtn.setOnClickListener(v -> {
                try {
                    startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
                } catch (Exception e) {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())));
                }
            });
            root.addView(overlayBtn);

            TextView hint = new TextView(this);
            hint.setText("Find \"Display over other apps\" and enable it, then press Continue below");
            hint.setTextSize(12f);
            hint.setTextColor(0xFF666666);
            hint.setPadding(0, 4, 0, 8);
            root.addView(hint);

            Button confirmBtn = new Button(this);
            confirmBtn.setText("2. Permission granted — continue");
            confirmBtn.setBackgroundColor(0xFF4CAF50);
            confirmBtn.setTextColor(0xFFFFFFFF);
            confirmBtn.setOnClickListener(v -> {
                prefs.edit().putBoolean("overlay_manual_granted", true).apply();
                recreate();
            });
            root.addView(confirmBtn);
        } else {
            // Overlay settings (always visible when permission granted)
            Button overlaySettingsBtn = new Button(this);
            overlaySettingsBtn.setText("Overlay settings");
            overlaySettingsBtn.setOnClickListener(v -> {
                try {
                    startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
                } catch (Exception e) {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())));
                }
            });
            root.addView(overlaySettingsBtn);

            Button testBtn = new Button(this);
            testBtn.setText("Test overlay");
            testBtn.setOnClickListener(v -> {
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
            root.addView(testBtn);
        }

        // All good indicator
        if (isAccEnabled && hasOverlay) {
            TextView ok = new TextView(this);
            ok.setText("\nAll permissions OK — open Deepal app (深蓝汽车)");
            ok.setTextSize(14f);
            ok.setTextColor(0xFF4CAF50);
            ok.setPadding(0, 12, 0, 8);
            root.addView(ok);

            // Open Deepal button
            Button openDeepalBtn = new Button(this);
            openDeepalBtn.setText("Open Deepal (深蓝汽车)");
            openDeepalBtn.setBackgroundColor(0xFF1C58F6);
            openDeepalBtn.setTextColor(0xFFFFFFFF);
            openDeepalBtn.setTextSize(15f);
            openDeepalBtn.setPadding(0, 12, 0, 12);
            openDeepalBtn.setOnClickListener(v -> {
                try {
                    // Try standard launch intent first
                    Intent launch = getPackageManager().getLaunchIntentForPackage("deepal.com.cn.app");
                    if (launch != null) {
                        startActivity(launch);
                    } else {
                        // Fallback: try known SplashActivity
                        Intent intent = new Intent();
                        intent.setClassName("deepal.com.cn.app", "deepal.com.cn.app.SplashActivity");
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(intent);
                    }
                } catch (Exception e) {
                    Toast.makeText(this, "Deepal app not found", Toast.LENGTH_SHORT).show();
                }
            });
            root.addView(openDeepalBtn);
        }

        // Separator
        View sep = new View(this);
        sep.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 1));
        sep.setBackgroundColor(0xFFCCCCCC);
        sep.setPadding(0, 16, 0, 16);
        root.addView(sep);

        // === Settings ===
        TextView settingsTitle = new TextView(this);
        settingsTitle.setText("Settings");
        settingsTitle.setTextSize(18f);
        settingsTitle.setPadding(0, 8, 0, 12);
        root.addView(settingsTitle);

        // Language
        TextView langLabel = new TextView(this);
        langLabel.setText("Translation language:");
        langLabel.setTextSize(14f);
        root.addView(langLabel);

        String[] languages = {"English", "Russian"};
        Spinner langSpinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
            android.R.layout.simple_spinner_item, languages);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        langSpinner.setAdapter(adapter);
        langSpinner.setSelection(prefs.getInt("target_lang", 0));
        root.addView(langSpinner);

        // Scan all
        CheckBox scanAllBox = new CheckBox(this);
        scanAllBox.setText("Scan ALL apps (debug)");
        scanAllBox.setTextSize(14f);
        scanAllBox.setChecked(prefs.getBoolean("scan_all", true));
        scanAllBox.setPadding(0, 12, 0, 8);
        root.addView(scanAllBox);

        // Save
        Button saveBtn = new Button(this);
        saveBtn.setText("Apply");
        saveBtn.setPadding(0, 20, 0, 16);
        saveBtn.setBackgroundColor(0xFF4CAF50);
        saveBtn.setTextColor(0xFFFFFFFF);
        saveBtn.setTextSize(16f);
        saveBtn.setOnClickListener(v -> {
            prefs.edit()
                .putInt("target_lang", langSpinner.getSelectedItemPosition())
                .putBoolean("scan_all", scanAllBox.isChecked())
                .apply();
            Toast.makeText(this, "Applied", Toast.LENGTH_SHORT).show();
            stopService(new Intent(this, TranslationService.class));
            startService(new Intent(this, TranslationService.class));
        });
        root.addView(saveBtn);

        // Debug log
        TextView logLabel = new TextView(this);
        logLabel.setText("\nCheck notification for scan details");
        logLabel.setTextSize(12f);
        logLabel.setTextColor(0xFF999999);
        root.addView(logLabel);

        // Quit button
        Button quitBtn = new Button(this);
        quitBtn.setText("Quit");
        quitBtn.setBackgroundColor(0xFFE53935);
        quitBtn.setTextColor(0xFFFFFFFF);
        quitBtn.setTextSize(14f);
        quitBtn.setPadding(0, 20, 0, 16);
        quitBtn.setOnClickListener(v -> {
            // Disable translation via preference, then close
            prefs.edit().putBoolean("translation_enabled", false).apply();
            stopService(new Intent(this, TranslationService.class));
            finishAffinity();
            System.exit(0);
        });
        root.addView(quitBtn);

        scroll.addView(root);
        setContentView(scroll);
    }
}
