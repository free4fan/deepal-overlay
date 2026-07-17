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
import java.util.concurrent.ConcurrentHashMap;
import org.json.JSONObject;
import org.json.JSONException;

public class TranslationService extends android.accessibilityservice.AccessibilityService {
    private static final String TAG = "DeepalTranslate";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "translation_channel";
    private static final long DEBOUNCE_MS = 350;

    private OverlayView statusView;
    private InlineOverlayManager inlineManager;
    private Handler mainHandler = new Handler(Looper.getMainLooper());
    private NotificationManager notificationManager;
    private int translateCount = 0;
    private String lastPackage = "";
    private long lastScanTime = 0;
    private String lastWindowPackage = "";
    private boolean translating = false;
    private final Map<String, String> translationCache = new ConcurrentHashMap<>();
    private Map<String, String> dictEn = new HashMap<>();
    private Map<String, String> dictRu = new HashMap<>();
    private boolean dictLoaded = false;
    private int lastTargetLang = -1;

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
        loadDictionary();
    }

    private void loadDictionary() {
        new Thread(() -> {
            try {
                dictEn = loadDictFromAssets("dict_zh_en.json");
                dictRu = loadDictFromAssets("dict_zh_ru.json");
                dictLoaded = true;
                Log.i(TAG, "Dictionary loaded: EN=" + dictEn.size() + " RU=" + dictRu.size());
                updateNotification("Dict loaded: " + dictEn.size() + " entries");
            } catch (Exception e) {
                Log.e(TAG, "Dictionary load failed: " + e.getMessage());
            }
        }).start();
    }

    private Map<String, String> loadDictFromAssets(String filename) throws IOException {
        Map<String, String> dict = new HashMap<>();
        try {
            InputStream is = getAssets().open(filename);
            BufferedReader r = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            r.close();
            JSONObject json = new JSONObject(sb.toString());
            java.util.Iterator<String> keys = json.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                dict.put(key, json.getString(key));
            }
        } catch (JSONException e) {
            throw new IOException("JSON parse error: " + e.getMessage());
        }
        return dict;
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

        // Detect leaving target app — only clear when package actually changes
        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CharSequence pkg = event.getPackageName();
            if (pkg != null) {
                String packageName = pkg.toString();
                if (!packageName.equals(lastWindowPackage)) {
                    lastWindowPackage = packageName;
                    SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
                    boolean scanAll = prefs.getBoolean("scan_all", true);
                    boolean isTarget = scanAll ||
                        packageName.contains("deepal") ||
                        packageName.contains("changan") ||
                        packageName.contains("cn.app");

                    if (!isTarget) {
                        mainHandler.post(() -> {
                            if (inlineManager != null) inlineManager.clearAll();
                        });
                        return;
                    }
                }
            }
        }

        // Debounced scan — no clearAll on scroll, positions update in-place
        long now = System.currentTimeMillis();
        if (now - lastScanTime < DEBOUNCE_MS) return;
        lastScanTime = now;
        mainHandler.post(this::scanWindow);
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

        int targetLang = prefs.getInt("target_lang", 0);
        // Clear cache when language changes
        if (targetLang != lastTargetLang) {
            lastTargetLang = targetLang;
            translationCache.clear();
            mainHandler.post(() -> inlineManager.clearAll());
        }
        final Map<String, String> dict = (targetLang == 0) ? dictEn : dictRu;

        // Lookup in dictionary first — instant, no API needed
        final Set<String> currentPositions = new HashSet<>();
        final List<TextNodeInfo> toTranslate = new ArrayList<>();

        for (TextNodeInfo node : chineseNodes) {
            String dictResult = dictLoaded ? dict.get(node.text) : null;
            if (dictResult == null) dictResult = translationCache.get(node.text);
            String display = dictResult != null ? dictResult : node.text;
            currentPositions.add(node.bounds.left + "," + node.bounds.top);
            if (dictResult == null) {
                toTranslate.add(node);
            }
        }

        final List<TextNodeInfo> nodesToShow = new ArrayList<>(chineseNodes);
        mainHandler.post(() -> {
            inlineManager.removeNotIn(currentPositions);
            for (TextNodeInfo node : nodesToShow) {
                String dictResult = dictLoaded ? dict.get(node.text) : null;
                if (dictResult == null) dictResult = translationCache.get(node.text);
                String display = dictResult != null ? dictResult : node.text;
                inlineManager.showTranslation(
                    node.bounds.left, node.bounds.top,
                    node.bounds.width(), node.bounds.height(),
                    display, node.estimatedTextSize, node.bgColor);
            }
        });

        if (!toTranslate.isEmpty() && !translating) {
            updateNotification("Translating " + toTranslate.size() + " new...");
            translateBatch(toTranslate);
        }
    }

    private void collectChineseNodes(AccessibilityNodeInfo node, List<TextNodeInfo> result) {
        collectChineseNodes(node, result, 0);
    }

    private void collectChineseNodes(AccessibilityNodeInfo node, List<TextNodeInfo> result, int depth) {
        if (node == null || depth > 50) return;

        CharSequence text = node.getText();
        if (text != null && text.length() > 0) {
            String s = text.toString().trim();
            if (hasChinese(s) && s.length() <= 200) {
                Rect bounds = new Rect();
                node.getBoundsInScreen(bounds);
                float textSize = estimateTextSize(node);
                int bgColor = detectBackgroundColor(node);
                result.add(new TextNodeInfo(s, bounds, textSize, bgColor));
            }
        }

        int childCount = node.getChildCount();
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collectChineseNodes(child, result, depth + 1);
            }
        }
    }

    private int detectBackgroundColor(AccessibilityNodeInfo node) {
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        float density = getResources().getDisplayMetrics().density;

        // Only check nearest 3 parents
        AccessibilityNodeInfo parent = node.getParent();
        int levels = 0;
        while (parent != null && levels < 3) {
            String viewId = parent.getViewIdResourceName();
            if (viewId != null) {
                String id = viewId.toLowerCase();
                if (id.contains("toolbar") || id.contains("appbar")) {
                    return 0xFF202020;
                }
            }
            CharSequence className = parent.getClassName();
            if (className != null) {
                String cn = className.toString();
                if (cn.endsWith("Toolbar") || cn.endsWith("AppBarLayout")) {
                    return 0xFF202020;
                }
            }
            parent = parent.getParent();
            levels++;
        }

        // Top 80dp — likely in header/toolbar zone
        if (bounds.top < 80 * density) {
            return 0xFF202020;
        }

        return 0xFFFFFFFF;
    }

    private float estimateTextSize(AccessibilityNodeInfo node) {
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        int height = bounds.height();
        float density = getResources().getDisplayMetrics().density;
        float heightDp = height / density;
        return Math.max(10, Math.min(heightDp * 0.65f, 26));
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
                    final int bg = node.bgColor;

                    mainHandler.post(() -> {
                        inlineManager.showTranslation(l, t, w, h, translated, sz, bg);
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
        int bgColor;

        TextNodeInfo(String text, Rect bounds, float estimatedTextSize, int bgColor) {
            this.text = text;
            this.bounds = bounds;
            this.estimatedTextSize = estimatedTextSize;
            this.bgColor = bgColor;
        }
    }
}
