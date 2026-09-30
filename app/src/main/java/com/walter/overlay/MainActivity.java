package com.walter.overlay;

import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.PixelFormat;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.ImageView;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AppCompatDelegate;
import androidx.core.content.ContextCompat;
import androidx.core.view.WindowCompat;
import com.google.android.material.appbar.MaterialToolbar;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.materialswitch.MaterialSwitch;
import com.google.android.material.card.MaterialCardView;
import java.util.Locale;

public class MainActivity extends AppCompatActivity {
    private MaterialButton accBtn, grantOverlayBtn, openDeepalBtn, testOverlayBtn;
    private MaterialButton quitKeepAccBtn, quitDisableAccBtn;
    private MaterialCardView actionsCard;
    private ImageView accIcon, overlayIcon;
    private TextView accStatusLabel, overlayStatusLabel;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        applyTheme();
        applyLocale();
        super.onCreate(savedInstanceState);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        setContentView(R.layout.activity_main);

        ((MaterialToolbar) findViewById(R.id.toolbar)).setSubtitle("v" + BuildConfig.VERSION_NAME);

        accBtn = findViewById(R.id.accBtn);
        quitKeepAccBtn = findViewById(R.id.quitKeepAccBtn);
        quitDisableAccBtn = findViewById(R.id.quitDisableAccBtn);
        openDeepalBtn = findViewById(R.id.openDeepalBtn);
        testOverlayBtn = findViewById(R.id.testOverlayBtn);
        actionsCard = findViewById(R.id.actionsCard);
        grantOverlayBtn = findViewById(R.id.grantOverlayBtn);
        MaterialSwitch scanAllSwitch = findViewById(R.id.scanAllSwitch);
        MaterialSwitch wordWrapSwitch = findViewById(R.id.wordWrapSwitch);
        MaterialSwitch darkOverlaySwitch = findViewById(R.id.darkOverlaySwitch);
        MaterialButtonToggleGroup langToggle = findViewById(R.id.langToggle);
        MaterialButton langEn = findViewById(R.id.langEn);
        MaterialButton langRu = findViewById(R.id.langRu);
        MaterialButtonToggleGroup uiLangToggle = findViewById(R.id.uiLangToggle);
        MaterialButton uiLangEn = findViewById(R.id.uiLangEn);
        MaterialButton uiLangRu = findViewById(R.id.uiLangRu);
        MaterialButtonToggleGroup themeToggle = findViewById(R.id.themeToggle);
        MaterialButton themeLight = findViewById(R.id.themeLight);
        MaterialButton themeDark = findViewById(R.id.themeDark);
        MaterialButton themeSystem = findViewById(R.id.themeSystem);

        prefs = getSharedPreferences("deepal", MODE_PRIVATE);

        // Status icons
        accIcon = findViewById(R.id.accIcon);
        overlayIcon = findViewById(R.id.overlayIcon);
        accStatusLabel = findViewById(R.id.accStatusLabel);
        overlayStatusLabel = findViewById(R.id.overlayStatusLabel);

        refreshStatus();

        // Actions card button listeners (visibility set in refreshStatus)
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
                Toast.makeText(this, R.string.deepal_not_found, Toast.LENGTH_SHORT).show();
            }
        });

        testOverlayBtn.setOnClickListener(v -> {
            try {
                WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
                TextView testView = new TextView(this);
                testView.setText(R.string.test_overlay_text);
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
                Toast.makeText(this, getString(R.string.error_prefix) + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        });

        // UI language toggle
        String uiLang = prefs.getString("ui_lang", "en");
        if ("ru".equals(uiLang)) {
            uiLangToggle.check(R.id.uiLangRu);
        } else {
            uiLangToggle.check(R.id.uiLangEn);
        }

        uiLangToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (!isChecked) return;
            String newLang = (checkedId == R.id.uiLangRu) ? "ru" : "en";
            if (!newLang.equals(uiLang)) {
                prefs.edit().putString("ui_lang", newLang).apply();
                recreate();
            }
        });

        // App theme toggle
        String themeMode = prefs.getString("theme_mode", "system");
        switch (themeMode) {
            case "light": themeToggle.check(R.id.themeLight); break;
            case "dark": themeToggle.check(R.id.themeDark); break;
            default: themeToggle.check(R.id.themeSystem); break;
        }

        themeToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (!isChecked) return;
            String newTheme;
            if (checkedId == R.id.themeLight) newTheme = "light";
            else if (checkedId == R.id.themeDark) newTheme = "dark";
            else newTheme = "system";
            if (!newTheme.equals(themeMode)) {
                prefs.edit().putString("theme_mode", newTheme).apply();
                applyTheme();
                recreate();
            }
        });

        // Translation language toggle
        if (prefs.getInt("target_lang", 0) == 0) {
            langToggle.check(R.id.langEn);
        } else {
            langToggle.check(R.id.langRu);
        }

        scanAllSwitch.setChecked(prefs.getBoolean("scan_all", false));
        wordWrapSwitch.setChecked(prefs.getBoolean("word_wrap", false));
        darkOverlaySwitch.setChecked(prefs.getBoolean("dark_overlay", false));

        // The service reads prefs on every scan — no need to restart it
        // (stopService is a no-op for an accessibility service anyway)
        langToggle.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (!isChecked) return;
            int langPos = checkedId == R.id.langRu ? 1 : 0;
            prefs.edit().putInt("target_lang", langPos).apply();
        });

        scanAllSwitch.setOnCheckedChangeListener((btn, checked) -> {
            prefs.edit().putBoolean("scan_all", checked).apply();
        });

        wordWrapSwitch.setOnCheckedChangeListener((btn, checked) -> {
            prefs.edit().putBoolean("word_wrap", checked).apply();
        });

        darkOverlaySwitch.setOnCheckedChangeListener((btn, checked) -> {
            prefs.edit().putBoolean("dark_overlay", checked).apply();
        });

        quitKeepAccBtn.setOnClickListener(v -> {
            TranslationService.disableTranslation();
            finishAndRemoveTask();
        });

        quitDisableAccBtn.setOnClickListener(v -> {
            TranslationService.quit();
            finishAndRemoveTask();
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        TranslationService.reactivate();
        refreshStatus();
    }

    private void refreshStatus() {
        String serviceId = getPackageName() + "/" + TranslationService.class.getName();
        String enabledServices = Settings.Secure.getString(getContentResolver(),
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean isAccEnabled = enabledServices != null && enabledServices.contains(serviceId);
        boolean hasOverlay = checkOverlayPermission();

        if (isAccEnabled) {
            accIcon.setImageResource(android.R.drawable.ic_menu_info_details);
            accIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_success));
            accStatusLabel.setText(R.string.acc_active);
            accBtn.setText(R.string.btn_enabled);
            accBtn.setEnabled(false);
            accBtn.setBackgroundTintList(ContextCompat.getColorStateList(this, R.color.status_success));
            accBtn.setTextColor(ContextCompat.getColor(this, android.R.color.white));
        } else {
            accIcon.setImageResource(android.R.drawable.ic_dialog_alert);
            accIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_error));
            accStatusLabel.setText(R.string.acc_required);
            accBtn.setEnabled(true);
            accBtn.setBackgroundTintList(null);
            accBtn.setTextColor(ContextCompat.getColor(this, R.color.md_theme_error));
            accBtn.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        }

        if (hasOverlay) {
            overlayIcon.setImageResource(android.R.drawable.ic_menu_info_details);
            overlayIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_success));
            overlayStatusLabel.setText(R.string.overlay_granted);
            grantOverlayBtn.setText(R.string.btn_overlay_granted);
            grantOverlayBtn.setEnabled(false);
            grantOverlayBtn.setBackgroundTintList(ContextCompat.getColorStateList(this, R.color.status_success));
            grantOverlayBtn.setTextColor(ContextCompat.getColor(this, android.R.color.white));
        } else {
            overlayIcon.setImageResource(android.R.drawable.ic_dialog_alert);
            overlayIcon.setColorFilter(ContextCompat.getColor(this, R.color.status_error));
            overlayStatusLabel.setText(R.string.overlay_required);
            grantOverlayBtn.setText(R.string.btn_grant_overlay);
            grantOverlayBtn.setEnabled(true);
            grantOverlayBtn.setBackgroundTintList(null);
            grantOverlayBtn.setTextColor(ContextCompat.getColor(this, R.color.md_theme_error));
            grantOverlayBtn.setOnClickListener(v -> {
                try {
                    startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
                } catch (Exception e) {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())));
                }
            });
        }

        actionsCard.setVisibility(isAccEnabled && hasOverlay ? android.view.View.VISIBLE : android.view.View.GONE);
    }

    // Build the new config from the current one: a bare Configuration() (the old
    // code) zeroed densityDpi and other fields after every language switch
    private void applyLocale() {
        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        String lang = prefs.getString("ui_lang", "en");
        Locale locale = new Locale(lang);
        Locale.setDefault(locale);
        android.content.res.Resources res = getBaseContext().getResources();
        Configuration config = res.getConfiguration();
        config.setLocale(locale);
        res.updateConfiguration(config, res.getDisplayMetrics());
    }

    private void applyTheme() {
        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        String themeMode = prefs.getString("theme_mode", "system");
        switch (themeMode) {
            case "light":
                AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_NO);
                break;
            case "dark":
                AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES);
                break;
            default:
                AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM);
                break;
        }
    }

    private boolean checkOverlayPermission() {
        return Settings.canDrawOverlays(this);
    }
}
