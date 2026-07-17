package com.walter.overlay;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
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
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class TranslationService extends android.accessibilityservice.AccessibilityService {
    private static final String TAG = "DeepalTranslate";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "translation_channel";
    private static final long DEBOUNCE_MS = 800;

    private OverlayView statusView;
    private InlineOverlayManager inlineManager;
    private Handler mainHandler = new Handler(Looper.getMainLooper());
    private NotificationManager notificationManager;
    private int translateCount = 0;
    private String lastPackage = "";
    private long lastScanTime = 0;
    private boolean translating = false;
    private final Map<String, String> translationCache = new HashMap<>();

    @Override
    public void onServiceConnected() {
        Log.i(TAG, "Service started");

        notificationManager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Deepal Translate",
                NotificationManager.IMPORTANCE_LOW);
            notificationManager.createNotificationChannel(channel);
        }

        updateNotification("Ready — open Deepal");

        android.accessibilityservice.AccessibilityServiceInfo config =
            new android.accessibilityservice.AccessibilityServiceInfo();
        config.eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED |
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED |
            AccessibilityEvent.TYPE_VIEW_FOCUSED |
            AccessibilityEvent.TYPE_VIEW_SCROLLED |
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED;
        config.feedbackType = android.accessibilityservice.AccessibilityServiceInfo.FEEDBACK_GENERIC;
        config.flags = android.accessibilityservice.AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS |
            android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS |
            android.accessibilityservice.AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS;
        config.notificationTimeout = 100;
        setServiceInfo(config);

        inlineManager = new InlineOverlayManager(this);
        setupStatusOverlay();
    }

    private int getStatusBarHeight() {
        int resourceId = getResources().getIdentifier("status_bar_height", "dimen", "android");
        if (resourceId > 0) return getResources().getDimensionPixelSize(resourceId);
        return 0;
    }

    private void setupStatusOverlay() {
        try {
            android.view.WindowManager wm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
            statusView = new OverlayView(this);
            statusView.setText("Deepal Translate ready");
            statusView.show();

            android.util.DisplayMetrics dm = new android.util.DisplayMetrics();
            wm.getDefaultDisplay().getMetrics(dm);

            android.view.WindowManager.LayoutParams params = new android.view.WindowManager.LayoutParams(
                dm.widthPixels / 2,
                android.view.WindowManager.LayoutParams.WRAP_CONTENT,
                android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE |
                    android.view.WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                android.graphics.PixelFormat.TRANSLUCENT);
            params.gravity = android.view.Gravity.TOP | android.view.Gravity.END;
            params.x = 10;
            params.y = getStatusBarHeight() + 10;
            params.alpha = 0.7f;
            wm.addView(statusView, params);
        } catch (Exception e) {
            Log.e(TAG, "Status overlay failed: " + e.getMessage());
        }
    }

    private void updateNotification(String text) {
        if (notificationManager == null) return;
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, intent,
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Deepal Translate v" + BuildConfig.VERSION_NAME)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_search)
            .setOngoing(true)
            .setContentIntent(pi)
            .build();

        notificationManager.notify(NOTIFICATION_ID, notification);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;

        int type = event.getEventType();

        // On window change: check if we left the target app
        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CharSequence pkg = event.getPackageName();
            if (pkg != null) {
                String packageName = pkg.toString();
                SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
                boolean scanAll = prefs.getBoolean("scan_all", true);
                boolean isTarget = scanAll ||
                    packageName.contains("deepal") ||
                    packageName.contains("changan") ||
                    packageName.contains("cn.app");

                if (!isTarget) {
                    // Left target app — clear all overlays
                    mainHandler.post(() -> {
                        if (inlineManager != null) inlineManager.clearAll();
                    });
                    return;
                }
            }
        }

        if (type == AccessibilityEvent.TYPE_VIEW_SCROLLED) {
            mainHandler.post(() -> {
                if (inlineManager != null) inlineManager.clearAll();
            });
        }

        // Debounced scan
        long now = System.currentTimeMillis();
        if (now - lastScanTime < DEBOUNCE_MS) return;
        lastScanTime = now;
        mainHandler.postDelayed(this::scanWindow, 100);
    }

    private void scanWindow() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;

        String packageName = root.getPackageName() != null ?
            root.getPackageName().toString() : "";

        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        boolean scanAll = prefs.getBoolean("scan_all", true);
        boolean isTarget = scanAll ||
            packageName.contains("deepal") ||
            packageName.contains("changan") ||
            packageName.contains("cn.app");

        if (!isTarget) {
            root.recycle();
            return;
        }

        if (!packageName.equals(lastPackage)) {
            lastPackage = packageName;
            translationCache.clear();
            mainHandler.post(() -> inlineManager.clearAll());
        }

        List<TextNodeInfo> chineseNodes = new ArrayList<>();
        collectChineseNodes(root, chineseNodes);
        root.recycle();

        if (chineseNodes.isEmpty()) {
            updateNotification(packageName + ": no Chinese text");
            return;
        }

        // Show cached translations immediately
        final Set<String> currentTexts = new HashSet<>();
        final List<TextNodeInfo> toTranslate = new ArrayList<>();

        for (TextNodeInfo node : chineseNodes) {
            String cached = translationCache.get(node.text);
            String display = cached != null ? cached : node.text;
            currentTexts.add(display);
            if (cached == null) {
                toTranslate.add(node);
            }
        }

        final List<TextNodeInfo> nodesToShow = new ArrayList<>(chineseNodes);
        mainHandler.post(() -> {
            inlineManager.removeNotIn(currentTexts);
            for (TextNodeInfo node : nodesToShow) {
                String cached = translationCache.get(node.text);
                String display = cached != null ? cached : node.text;
                inlineManager.showTranslation(
                    node.bounds.left, node.bounds.top,
                    node.bounds.width(), node.bounds.height(),
                    display, node.estimatedTextSize);
            }
        });

        if (!toTranslate.isEmpty() && !translating) {
            updateNotification("Translating " + toTranslate.size() + " new...");
            translateBatch(toTranslate);
        }
    }

    private void collectChineseNodes(AccessibilityNodeInfo node, List<TextNodeInfo> result) {
        if (node == null) return;

        CharSequence text = node.getText();
        if (text != null && text.length() > 0) {
            String s = text.toString().trim();
            if (hasChinese(s) && s.length() <= 200) {
                Rect bounds = new Rect();
                node.getBoundsInScreen(bounds);
                float textSize = estimateTextSize(node);
                result.add(new TextNodeInfo(s, bounds, textSize));
            }
        }

        int childCount = node.getChildCount();
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collectChineseNodes(child, result);
            }
        }
    }

    private float estimateTextSize(AccessibilityNodeInfo node) {
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        int height = bounds.height();
        float density = getResources().getDisplayMetrics().density;
        // Height in dp, font size is roughly 80% of view height for single-line text
        float heightDp = height / density;
        return Math.max(12, Math.min(heightDp * 0.85f, 30));
    }

    private void translateBatch(List<TextNodeInfo> nodes) {
        if (translating) return;
        translating = true;

        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        int targetLang = prefs.getInt("target_lang", 0);
        final String langCode = (targetLang == 0) ? "en" : "ru";

        new Thread(() -> {
            for (TextNodeInfo node : nodes) {
                try {
                    String result = translateText(node.text, langCode);
                    node.translated = result;
                    translationCache.put(node.text, result);
                    translateCount++;

                    final String translated = result;
                    final int l = node.bounds.left;
                    final int t = node.bounds.top;
                    final int w = node.bounds.width();
                    final int h = node.bounds.height();
                    final float sz = node.estimatedTextSize;

                    mainHandler.post(() -> {
                        inlineManager.showTranslation(l, t, w, h, translated, sz);
                    });
                } catch (Exception e) {
                    Log.e(TAG, "Translate error: " + e.getMessage());
                }
            }

            translating = false;
            updateNotification(translateCount + " translated (cache: " + translationCache.size() + ")");
        }).start();
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
        try (BufferedReader r = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
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
        try (BufferedReader r = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
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
    public void onInterrupt() {}

    @Override
    public void onDestroy() {
        super.onDestroy();
        mainHandler.post(() -> {
            if (inlineManager != null) inlineManager.clearAll();
            if (statusView != null) {
                try {
                    android.view.WindowManager wm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
                    wm.removeViewImmediate(statusView);
                } catch (Exception ignored) {}
            }
        });
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        stopSelf();
    }

    private static class TextNodeInfo {
        String text;
        Rect bounds;
        float estimatedTextSize;
        String translated;

        TextNodeInfo(String text, Rect bounds, float estimatedTextSize) {
            this.text = text;
            this.bounds = bounds;
            this.estimatedTextSize = estimatedTextSize;
        }
    }
}
