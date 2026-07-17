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
    private int translateCount = 0;

    @Override
    public void onServiceConnected() {
        Log.i(TAG, "TranslationService started");
        
        notificationManager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Deepal Translate",
                android.app.NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Translation status");
            notificationManager.createNotificationChannel(channel);
        }
        
        updateNotification("Ready — open Deepal app");

        android.accessibilityservice.AccessibilityServiceInfo config = 
            new android.accessibilityservice.AccessibilityServiceInfo();
        config.eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED |
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED |
            AccessibilityEvent.TYPE_VIEW_FOCUSED;
        config.feedbackType = android.accessibilityservice.AccessibilityServiceInfo.FEEDBACK_GENERIC;
        config.flags = android.accessibilityservice.AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS |
            android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS |
            android.accessibilityservice.AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS;
        config.notificationTimeout = 50;
        setServiceInfo(config);

        setupOverlay();
        
        scheduler = Executors.newSingleThreadScheduledExecutor();
        scheduler.scheduleAtFixedRate(this::scanWindow, 0, 2000, TimeUnit.MILLISECONDS);
    }

    private void updateNotification(String text) {
        if (notificationManager == null) return;
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
            this, 0, intent, 
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT
        );
        
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Deepal Translate v" + BuildConfig.VERSION_NAME)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_search)
            .setOngoing(true)
            .setContentIntent(pi)
            .build();
        
        notificationManager.notify(NOTIFICATION_ID, notification);
    }

    private void setupOverlay() {
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        if (overlayView != null) return;

        overlayView = new OverlayView(this);
        
        DisplayMetrics dm = new DisplayMetrics();
        windowManager.getDefaultDisplay().getMetrics(dm);

        int widthPx = (int)(dm.widthPixels * 0.92);
        
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
            widthPx,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            android.graphics.PixelFormat.TRANSLUCENT);

        params.gravity = Gravity.BOTTOM;
        params.y = 20;
        params.x = (dm.widthPixels - widthPx) / 2;
        params.alpha = 0.95f;

        try {
            windowManager.addView(overlayView, params);
            overlayView.setText("Deepal Translate v" + BuildConfig.VERSION_NAME + "\nWaiting for app...");
            overlayView.show();
            Log.i(TAG, "Overlay added successfully");
        } catch (Exception e) {
            Log.e(TAG, "Overlay failed: " + e.getMessage());
            overlayView = null;
        }
    }

    private void scanWindow() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        
        if (root == null) {
            scanCount++;
            if (scanCount % 5 == 0) {
                updateNotification("Scan #" + scanCount + " — no active window");
            }
            return;
        }

        String packageName = root.getPackageName() != null ? 
            root.getPackageName().toString() : "unknown";
        String className = root.getClassName() != null ? root.getClassName().toString() : "unknown";
        
        scanCount++;
        
        SharedPreferences prefs2 = getSharedPreferences("deepal", MODE_PRIVATE);
        boolean scanAll = prefs2.getBoolean("scan_all", true);
        boolean isTarget = scanAll ||
                          packageName.contains("deepal") || 
                          packageName.contains("changan") ||
                          packageName.contains("cn.app");

        if (!isTarget) {
            root.recycle();
            return;
        }

        Log.d(TAG, "Scan #" + scanCount + " pkg=" + packageName + " class=" + className);
        updateNotification("Scanning: " + packageName + " (" + className.substring(className.lastIndexOf('.') + 1) + ")");

        List<String> allTexts = extractAllText(root);
        int childCount = root.getChildCount();
        root.recycle();
        
        if (allTexts.isEmpty()) {
            final String debug = "📱 " + packageName + "\n⚠️ No text nodes found\nClass: " + 
                className.substring(className.lastIndexOf('.') + 1) + 
                "\nChildren: " + childCount;
            mainHandler.post(() -> {
                if (overlayView != null) {
                    overlayView.setText(debug);
                    overlayView.show();
                }
                updateNotification("No text in " + packageName + " (children=" + childCount + ")");
            });
            return;
        }

        String chineseText = null;
        for (String t : allTexts) {
            if (hasChinese(t)) {
                chineseText = t;
                break;
            }
        }

        if (chineseText != null) {
            final String textToTranslate = chineseText;
            String displayText = textToTranslate.length() > 60 ? 
                textToTranslate.substring(0, 57) + "..." : textToTranslate;
            
            mainHandler.post(() -> {
                if (overlayView != null) {
                    overlayView.setText("CN: " + displayText);
                    overlayView.show();
                }
                updateNotification("Found CN: " + displayText);
            });

            if (!isTranslating) {
                isTranslating = true;
                SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
                int targetLang = prefs.getInt("target_lang", 0);
                final String langCode = (targetLang == 0) ? "en" : "ru";

                new Thread(() -> {
                    try {
                        String result = translateText(textToTranslate, langCode);
                        translateCount++;
                        mainHandler.post(() -> {
                            if (overlayView != null && result != null) {
                                overlayView.setText(result);
                            }
                            updateNotification("Translated #" + translateCount + ": " + 
                                (result != null ? result : textToTranslate));
                        });
                    } catch (Exception e) {
                        Log.e(TAG, "Translation error: " + e.getMessage());
                        mainHandler.post(() -> {
                            if (overlayView != null) overlayView.setText("Error: " + e.getMessage());
                            updateNotification("Translation error: " + e.getMessage());
                        });
                    } finally {
                        isTranslating = false;
                    }
                }).start();
            }
        } else {
            final int textCount = allTexts.size();
            StringBuilder debug = new StringBuilder();
            debug.append("📱 ").append(packageName).append("\n");
            debug.append("📝 Texts: ").append(textCount).append(" (no Chinese)\n");
            for (int i = 0; i < Math.min(4, textCount); i++) {
                String t = allTexts.get(i);
                debug.append(t.length() > 35 ? t.substring(0,32)+"..." : t).append("\n");
            }
            final String debugText = debug.toString();
            mainHandler.post(() -> {
                if (overlayView != null) {
                    overlayView.setText(debugText);
                    overlayView.show();
                }
                updateNotification("Texts: " + textCount + " (no Chinese detected)");
            });
        }
        
        lastScanTime = System.currentTimeMillis();
    }

    private List<String> extractAllText(AccessibilityNodeInfo node) {
        List<String> texts = new ArrayList<>();
        if (node == null) return texts;

        CharSequence text = node.getText();
        if (text != null && text.length() > 0) {
            String s = text.toString().trim();
            if (s.length() >= 1 && s.length() <= 300) {
                texts.add(s);
            }
        }

        CharSequence desc = node.getContentDescription();
        if (desc != null && desc.length() > 0) {
            String s = desc.toString().trim();
            if (s.length() >= 1 && s.length() <= 300) {
                texts.add("[desc]" + s);
            }
        }

        int childCount = node.getChildCount();
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                texts.addAll(extractAllText(child));
            }
        }

        return texts;
    }

    private boolean hasChinese(String text) {
        if (text == null || text.length() == 0) return false;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if ((c >= 0x4E00 && c <= 0x9FFF) ||
                (c >= 0x3400 && c <= 0x4DBF) ||
                (c >= 0xF900 && c <= 0xFAFF)) {
                return true;
            }
        }
        return false;
    }

    private String translateText(String text, String langCode) throws IOException {
        try {
            return translateGoogle(text, langCode);
        } catch (Exception e1) {
            Log.w(TAG, "Google failed: " + e1.getMessage());
            try {
                return translateAlternative(text, langCode);
            } catch (Exception e2) {
                throw new IOException("All APIs failed: " + e1.getMessage());
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
        if (code != 200) throw new IOException("HTTP " + code);

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
        throw new IOException("Parse error");
    }

    private String translateAlternative(String text, String langCode) throws IOException {
        String encoded = java.net.URLEncoder.encode(text, "UTF-8");
        String urlStr = "https://api.mymemory.translated.net/get?q=" + encoded +
            "&langpair=zh-CN|" + langCode;

        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(15000);
        conn.setRequestProperty("User-Agent", "Mozilla/5.0");
        
        int code = conn.getResponseCode();
        if (code != 200) throw new IOException("HTTP " + code);

        InputStream is = conn.getInputStream();
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(
                new InputStreamReader(is, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
        }
        conn.disconnect();

        String json = sb.toString();
        int idx = json.indexOf("\"translatedText\":\"");
        if (idx > 0) {
            int start = idx + 17;
            int end = json.indexOf("\"", start);
            if (end > start) return json.substring(start, end);
        }
        throw new IOException("Parse error");
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
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
