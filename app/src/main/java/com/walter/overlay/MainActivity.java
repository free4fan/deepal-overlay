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
        // Try standard API first
        if (Settings.canDrawOverlays(this)) return true;
        // Fallback: check our manual flag
        return getSharedPreferences("deepal", MODE_PRIVATE)
            .getBoolean("overlay_manual_granted", false);
    }

    private void buildUI() {
        android.content.SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 48, 32, 32);
        root.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT));

        // Title
        TextView title = new TextView(this);
        title.setText("Deepal Translate v" + BuildConfig.VERSION_NAME);
        title.setTextSize(24f);
        title.setPadding(0, 0, 0, 8);
        root.addView(title);

        // Accessibility service status
        String serviceId = getPackageName() + "/" + TranslationService.class.getName();
        String enabledServices = Settings.Secure.getString(getContentResolver(),
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        boolean isAccessibilityEnabled = enabledServices != null && enabledServices.contains(serviceId);

        TextView accLabel = new TextView(this);
        accLabel.setText(isAccessibilityEnabled ? "✅ Сервис доступности включён" : "⛔ Сервис доступности выключен");
        accLabel.setTextSize(16f);
        accLabel.setPadding(0, 8, 0, 8);
        root.addView(accLabel);

        Button accBtn = new Button(this);
        if (!isAccessibilityEnabled) {
            accBtn.setText("Включить сервис доступности");
            accBtn.setOnClickListener(v -> {
                Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
                startActivity(intent);
            });
        } else {
            accBtn.setText("Доступность OK");
            accBtn.setEnabled(false);
            accBtn.setBackgroundColor(0xFF4CAF50);
            accBtn.setTextColor(0xFFFFFFFF);
        }
        root.addView(accBtn);

        // Overlay permission
        boolean hasOverlay = checkOverlayPermission();
        TextView overlayLabel = new TextView(this);
        overlayLabel.setText(hasOverlay ? "✅ Разрешение на оверлей получено" : "⛔ Разрешение на оверлей НЕ выдано");
        overlayLabel.setTextSize(16f);
        overlayLabel.setPadding(0, 16, 0, 8);
        root.addView(overlayLabel);

        if (!hasOverlay) {
            Button overlayBtn = new Button(this);
            overlayBtn.setText("1. Открыть настройки оверлея");
            overlayBtn.setOnClickListener(v -> {
                Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
                startActivity(intent);
            });
            root.addView(overlayBtn);

            Button confirmBtn = new Button(this);
            confirmBtn.setText("2. Я выдал разрешение — проверить");
            confirmBtn.setBackgroundColor(0xFFFF9800);
            confirmBtn.setTextColor(0xFFFFFFFF);
            confirmBtn.setOnClickListener(v -> {
                // Try to actually test if overlay works
                if (Settings.canDrawOverlays(this)) {
                    prefs.edit().putBoolean("overlay_manual_granted", true).apply();
                    recreate();
                } else {
                    // Try adding a temporary view to test
                    try {
                        WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
                        TextView testView = new TextView(this);
                        testView.setText("Тест");
                        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                            ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                            : WindowManager.LayoutParams.TYPE_PHONE;
                        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                            1, 1, type,
                            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                            PixelFormat.TRANSLUCENT);
                        params.gravity = Gravity.TOP;
                        wm.addView(testView, params);
                        wm.removeView(testView);
                        // If we got here, overlay works!
                        prefs.edit().putBoolean("overlay_manual_granted", true).apply();
                        recreate();
                    } catch (Exception e) {
                        Toast.makeText(this,
                            "Оверлей не работает: " + e.getMessage(),
                            Toast.LENGTH_LONG).show();
                    }
                }
            });
            root.addView(confirmBtn);
        } else {
            // Test overlay button
            Button testBtn = new Button(this);
            testBtn.setText("Тест оверлея");
            testBtn.setOnClickListener(v -> {
                try {
                    WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
                    TextView testView = new TextView(this);
                    testView.setText(" Тест оверлея работает! ");
                    testView.setTextSize(20f);
                    testView.setBackgroundColor(0xCC000000);
                    testView.setTextColor(0xFFFFFFFF);
                    testView.setPadding(24, 16, 24, 16);
                    int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                        ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                        : WindowManager.LayoutParams.TYPE_PHONE;
                    WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                        WindowManager.LayoutParams.WRAP_CONTENT,
                        WindowManager.LayoutParams.WRAP_CONTENT,
                        type,
                        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                        PixelFormat.TRANSLUCENT);
                    params.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
                    params.y = 200;
                    wm.addView(testView, params);
                    testView.postDelayed(() -> {
                        try { wm.removeView(testView); } catch (Exception ignored) {}
                    }, 3000);
                    Toast.makeText(this, "Оверлей работает!", Toast.LENGTH_SHORT).show();
                } catch (Exception e) {
                    Toast.makeText(this, "Ошибка: " + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            });
            root.addView(testBtn);
        }

        // Status summary
        if (isAccessibilityEnabled && hasOverlay) {
            TextView ok = new TextView(this);
            ok.setText("\n✅ Все разрешения выданы!\nНажмите \"Применить\" и откройте Deepal");
            ok.setTextSize(14f);
            ok.setTextColor(0xFF4CAF50);
            ok.setPadding(0, 16, 0, 8);
            root.addView(ok);
        }

        // Separator
        View sep = new View(this);
        sep.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 2));
        sep.setBackgroundColor(0xFFCCCCCC);
        sep.setPadding(0, 16, 0, 16);
        root.addView(sep);

        // Language selection
        TextView langLabel = new TextView(this);
        langLabel.setText("Язык перевода:");
        langLabel.setTextSize(16f);
        langLabel.setPadding(0, 8, 0, 8);
        root.addView(langLabel);

        String[] languages = {"English", "Русский"};
        Spinner langSpinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
            android.R.layout.simple_spinner_item, languages);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        langSpinner.setAdapter(adapter);
        langSpinner.setSelection(prefs.getInt("target_lang", 0));
        root.addView(langSpinner);

        // Scan all apps checkbox
        CheckBox scanAllBox = new CheckBox(this);
        scanAllBox.setText("Сканировать ВСЕ приложения (для отладки)");
        scanAllBox.setTextSize(14f);
        scanAllBox.setChecked(prefs.getBoolean("scan_all", true));
        scanAllBox.setPadding(0, 16, 0, 8);
        root.addView(scanAllBox);

        // Save button
        Button saveBtn = new Button(this);
        saveBtn.setText("Применить");
        saveBtn.setPadding(0, 24, 0, 16);
        saveBtn.setBackgroundColor(0xFF4CAF50);
        saveBtn.setTextColor(0xFFFFFFFF);
        saveBtn.setTextSize(18f);
        saveBtn.setOnClickListener(v -> {
            prefs.edit()
                .putInt("target_lang", langSpinner.getSelectedItemPosition())
                .putBoolean("scan_all", scanAllBox.isChecked())
                .apply();
            Toast.makeText(this, "Настройки применены", Toast.LENGTH_SHORT).show();

            stopService(new Intent(this, TranslationService.class));
            startService(new Intent(this, TranslationService.class));
        });
        root.addView(saveBtn);

        setContentView(root);
    }
}
