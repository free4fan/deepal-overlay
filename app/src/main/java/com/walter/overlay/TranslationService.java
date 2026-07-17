package com.walter.overlay;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.Gravity;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class TranslationService extends android.accessibilityservice.AccessibilityService {
    private static final String TAG = "DeepalTranslate";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "translation_channel";

    private OverlayView overlayView;
    private WindowManager windowManager;
    private Handler mainHandler = new Handler(Looper.getMainLooper());
    private ScheduledExecutorService scheduler;
    private NotificationManager notificationManager;
    private boolean isTranslating = false;
    private long lastScanTime = 0;
    private int scanCount = 0;

    @Override
    public void onServiceConnected() {
        Log.i(TAG, "TranslationService started");
        
        // Setup notification channel
        notificationManager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Deepal Переводчик",
                android.app.NotificationManager.IMPORTANCE_HIGH
            );
            channel.setDescription("Перевод текста из приложений");
            channel.setLockscreenVisibility(android.app.Notification.VISIBILITY_PUBLIC);
            notificationManager.createNotificationChannel(channel);
        }
        
        updateStatus("✅ Запущен! Откройте Deepal", 5000);

        // Configure accessibility service for full content capture
        android.accessibilityservice.AccessibilityServiceInfo config = 
            new android.accessibilityservice.AccessibilityServiceInfo();
        config.eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED |
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED;
        config.feedbackType = android.accessibilityservice.AccessibilityServiceInfo.FEEDBACK_SPOKEN;
        config.flags = android.accessibilityservice.AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS |
            android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        config.notificationTimeout = 100;
        setServiceInfo(config);

        // Setup overlay
        setupOverlay();
        
        // Start scan thread - every 2 seconds
        scheduler = Executors.newSingleThreadScheduledExecutor();
        scheduler.scheduleAtFixedRate(this::scanWindow, 0, 2000, TimeUnit.MILLISECONDS);
    }

    private void updateStatus(String text) {
        updateStatus(text, 3000);
    }

    private void updateStatus(String text, long durationMs) {
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
            this, 0, intent, 
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT
        );
        
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Deepal Translate v" + BuildConfig.VERSION_NAME)
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(pi)
            .build();
        
        notificationManager.notify(NOTIFICATION_ID, notification);
    }

    private void setupOverlay() {
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        if (overlayView != null) return;

        overlayView = new OverlayView(this);
        
        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        int alphaVal = prefs.getInt("overlay_alpha", 180);

        DisplayMetrics dm = new DisplayMetrics();
        ((WindowManager)getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getMetrics(dm);

        int widthPx = (int)(dm.widthPixels * 0.92);
        
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            widthPx,
            WindowManager.LayoutParams.WRAP_CONTENT,
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.O 
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            android.graphics.PixelFormat.TRANSLUCENT);

        params.gravity = Gravity.BOTTOM;
        params.y = 0;
        params.x = (dm.widthPixels - widthPx) / 2;
        params.alpha = Math.max(0.5f, alphaVal / 255.0f);

        try {
            windowManager.addView(overlayView, params);
            Log.i(TAG, "Overlay added successfully");
        } catch (Exception e) {
            Log.e(TAG, "Overlay failed: " + e.getMessage());
        }
    }

    private void scanWindow() {
        long now = System.currentTimeMillis();
        if (now - lastScanTime < 1500) return; // Debounce
        
        AccessibilityNodeInfo root = getRootInActiveWindow();
        
        if (root == null) {
            scanCount++;
            if (scanCount % 30 == 0) {
                mainHandler.post(() -> updateStatus("⏸ Нет окна (scan #" + scanCount + ")"));
            }
            return;
        }

        String packageName = root.getPackageName() != null ? 
            root.getPackageName().toString() : "unknown";
        String className = root.getClassName() != null ? root.getClassName().toString() : "unknown";
        
        scanCount++;
        
        // Check if we're in Deepal app (or scan all in debug mode)
        SharedPreferences prefs2 = getSharedPreferences("deepal", MODE_PRIVATE);
        boolean scanAll = prefs2.getBoolean("scan_all", true);
        boolean isDeepal = scanAll ||
                          packageName.contains("deepal") || 
                          packageName.contains("changan") ||
                          packageName.contains("cn.app");

        if (!isDeepal) {
            // Show package name briefly for debugging (every 10th scan)
            if (scanCount % 10 == 0) {
                final String pkg = packageName;
                mainHandler.post(() -> updateStatus("🔍 " + pkg, 2000));
            }
            root.recycle();
            return;
        }

        Log.d(TAG, "Window scan #" + scanCount + ": " + packageName + "/" + className);

        // Extract ALL text from window for debugging
        List<String> allTexts = extractAllText(root);
        root.recycle();
        
        if (allTexts.isEmpty()) {
            final String pkg = packageName;
            mainHandler.post(() -> updateStatus("📱 " + pkg + "\nТекстов нет"));
            return;
        }

        // Check if any Chinese text exists
        String chineseText = null;
        for (String t : allTexts) {
            if (hasChinese(t)) {
                chineseText = t;
                break;
            }
        }

        if (chineseText != null) {
            final String textToTranslate = chineseText;
            Log.d(TAG, "Found Chinese: " + textToTranslate);
            
            // Show found text in overlay immediately for debugging
            String displayText = textToTranslate.length() > 80 ? 
                textToTranslate.substring(0, 77) + "..." : textToTranslate;
            
            mainHandler.post(() -> {
                if (overlayView != null) {
                    overlayView.setText("📝 " + displayText);
                    overlayView.show();
                }
                updateStatus("🇨🇳 " + displayText, 4000);
            });

            // Translate in background thread
            if (!isTranslating) {
                isTranslating = true;
                SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
                int targetLang = prefs.getInt("target_lang", 0);
                final String langCode = (targetLang == 0) ? "en" : "ru";

                new Thread(() -> {
                    try {
                        String result = translateText(textToTranslate, langCode);
                        mainHandler.post(() -> {
                            if (overlayView != null && result != null) {
                                overlayView.setText("🌐 " + 
                                    (result.length() > 80 ? result.substring(0, 77)+"..." : result));
                            }
                            updateStatus("🌐 " + 
                                (result != null ? result : textToTranslate), 6000);
                            isTranslating = false;
                        });
                    } catch (Exception e) {
                        Log.e(TAG, "Translation error: " + e.getMessage());
                        mainHandler.post(() -> {
                            if (overlayView != null) overlayView.setError();
                            updateStatus("❌ Ошибка: " + e.getMessage(), 5000);
                            isTranslating = false;
                        });
                    }
                }).start();
            }
        } else {
            // No Chinese text - show all detected texts for debugging
            if (allTexts.size() < 15) {
                String combined = "🔍 Text:\n" + String.join("\n", allTexts);
                mainHandler.post(() -> {
                    if (overlayView != null) {
                        overlayView.setText(combined.length() > 200 ? 
                            combined.substring(0, 197)+"..." : combined);
                        overlayView.show();
                    }
                });
            }
        }
        
        lastScanTime = System.currentTimeMillis();
    }

    private List<String> extractAllText(AccessibilityNodeInfo node) {
        List<String> texts = new ArrayList<>();
        if (node == null) return texts;

        // Get text from this node
        CharSequence text = node.getText();
        if (text != null && text.length() > 0) {
            String s = text.toString().trim();
            if (s.length() >= 1 && s.length() <= 300 && !s.matches("^[a-zA-Z@.:\\-+ ]+$")) {
                texts.add(s);
            }
        }

        // Get content description (for buttons/icons)
        CharSequence desc = node.getContentDescription();
        if (desc != null && desc.length() > 0) {
            String s = desc.toString().trim();
            if (s.length() >= 1 && s.length() <= 300) {
                texts.add("[icon]" + s);
            }
        }

        // Recurse into children
        int childCount = node.getChildCount();
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                List<String> childTexts = extractAllText(child);
                texts.addAll(childTexts);
                // Don't recycle here - parent might need it
            }
        }

        return texts;
    }

    private boolean hasChinese(String text) {
        if (text == null || text.length() == 0) return false;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            // CJK Unified Ideographs and extensions
            if ((c >= 0x4E00 && c <= 0x9FFF) ||
                (c >= 0x3400 && c <= 0x4DBF) ||
                (c >= 0xF900 && c <= 0xFAFF)) {
                return true;
            }
        }
        return false;
    }

    private String translateText(String text, String langCode) throws IOException {
        // Try Google Translate first
        try {
            return translateGoogle(text, langCode);
        } catch (Exception e1) {
            Log.w(TAG, "Google Translate failed: " + e1.getMessage());
            // Fallback to alternative endpoint
            try {
                return translateAlternative(text, langCode);
            } catch (Exception e2) {
                Log.e(TAG, "All translation APIs failed");
                throw new IOException("Translation failed: " + e1.getMessage());
            }
        }
    }

    private String translateGoogle(String text, String langCode) throws IOException {
        String encoded = java.net.URLEncoder.encode(text, "UTF-8");
        String urlStr = "https://translate.googleapis.com/translate_a/single?" +
            "client=gtx&sl=zh-CN&tl=" + langCode + "&dt=t&q=" + encoded;

        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(15000);
        conn.setRequestProperty("User-Agent", "Mozilla/5.0");
        
        int code = conn.getResponseCode();
        if (code != 200) {
            throw new IOException("HTTP " + code);
        }

        InputStream is = conn.getInputStream();
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(
                new InputStreamReader(is, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
        }
        conn.disconnect();

        String json = sb.toString();
        int start = json.indexOf("\"");
        if (start > 0) {
            int end = json.indexOf("\"", start + 1);
            if (end > start + 1) return json.substring(start + 1, end);
        }
        throw new IOException("Invalid response format");
    }

    private String translateAlternative(String text, String langCode) throws IOException {
        String encoded = java.net.URLEncoder.encode(text, "UTF-8");
        // Use MyMemory free translation API as fallback
        String urlStr = "https://api.mymemory.translated.net/get?q=" + encoded +
            "&langpair=zh-CN|" + langCode;

        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(15000);
        conn.setRequestProperty("User-Agent", "Mozilla/5.0");
        
        int code = conn.getResponseCode();
        if (code != 200) {
            throw new IOException("HTTP " + code);
        }

        InputStream is = conn.getInputStream();
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(
                new InputStreamReader(is, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
        }
        conn.disconnect();

        // Parse: {"responseData":{"translatedText":"..."}}
        String json = sb.toString();
        int idx = json.indexOf("\"translatedText\":\"");
        if (idx > 0) {
            int start = idx + 17;
            int end = json.indexOf("\"", start);
            if (end > start) return json.substring(start, end);
        }
        throw new IOException("Invalid response format");
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Force immediate scan on text changes
        lastScanTime = 0;
    }

    @Override
    public void onInterrupt() {}

    @Override
    public void onDestroy() {
        super.onDestroy();
        if (scheduler != null) scheduler.shutdownNow();
        if (overlayView != null && windowManager != null) {
            try { windowManager.removeView(overlayView); } catch (Exception ignored) {}
        }
        Log.i(TAG, "Service destroyed");
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        stopSelf();
    }
}
