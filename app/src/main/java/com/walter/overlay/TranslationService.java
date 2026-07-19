package com.walter.overlay;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;
import org.json.JSONObject;
import org.json.JSONException;

public class TranslationService extends android.accessibilityservice.AccessibilityService {
    private static final String TAG = "DeepalTranslate";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "translation_channel";
    private static final long DEBOUNCE_MS = 350;
    public static final String ACTION_QUIT = "com.walter.overlay.QUIT";
    public static final String ACTION_SHOW = "com.walter.overlay.SHOW";

    private OverlayView statusView;
    private InlineOverlayManager inlineManager;
    private Handler mainHandler = new Handler(Looper.getMainLooper());
    private NotificationManager notificationManager;
    private int translateCount = 0;
    private String lastPackage = "";
    private long lastScanTime = 0;
    private String lastWindowPackage = "";
    private volatile boolean translating = false;
    private final Map<String, String> translationCache = new ConcurrentHashMap<>();
    private Map<String, String> dictEn = new HashMap<>();
    private Map<String, String> dictRu = new HashMap<>();
    private volatile boolean dictLoaded = false;
    private int lastTargetLang = -1;
    private boolean translationEnabled = true;
    private android.widget.TextView toggleButton;
    private android.view.WindowManager toggleWm;
    private BroadcastReceiver quitReceiver;
    private ExecutorService translateExecutor;
    private final Runnable retryRunnable = this::retryOverlaysIfNeeded;
    private long lastNotificationTime = 0;
    private static final Pattern HTML_PATTERN = Pattern.compile("<[^>]+>");

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

        // Read saved translation state
        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        translationEnabled = prefs.getBoolean("translation_enabled", true);

        if (translationEnabled) {
            updateNotification("Ready — open Deepal");
            setupStatusOverlay();
            setupToggleButton();
            updateToggleButtonAppearance();
        } else {
            updateNotification("Disabled");
        }

        loadDictionary();
        translateExecutor = Executors.newSingleThreadExecutor();

        quitReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                String action = intent.getAction();
                if (ACTION_QUIT.equals(action)) {
                    translationEnabled = false;
                } else if (ACTION_SHOW.equals(action)) {
                    translationEnabled = true;
                    updateNotification("Ready — open Deepal");
                    if (statusView == null || statusView.getWindowToken() == null) {
                        setupStatusOverlay();
                    }
                    if (toggleButton == null) {
                        setupToggleButton();
                        updateToggleButtonAppearance();
                    }
                }
            }
        };
        IntentFilter filter = new IntentFilter(ACTION_QUIT);
        filter.addAction(ACTION_SHOW);
        registerReceiver(quitReceiver, filter, Context.RECEIVER_NOT_EXPORTED);

        retryOverlaysIfNeeded();
    }

    private void retryOverlaysIfNeeded() {
        if (!Settings.canDrawOverlays(this)) {
            mainHandler.postDelayed(retryRunnable, 2000);
            return;
        }
        if (toggleButton == null) {
            setupToggleButton();
        }
        if (statusView == null || statusView.getWindowToken() == null) {
            setupStatusOverlay();
        }
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
        StringBuilder sb = new StringBuilder();
        try (InputStream is = getAssets().open(filename);
             BufferedReader r = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
        } catch (IOException e) {
            throw e;
        }
        try {
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
        if (!Settings.canDrawOverlays(this)) {
            Log.w(TAG, "No overlay permission, skipping status overlay");
            return;
        }
        try {
            android.view.WindowManager wm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
            statusView = new OverlayView(this);
            statusView.setText("Deepal Translate ready");
            statusView.show();

            android.util.DisplayMetrics dm = getResources().getDisplayMetrics();

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

    private void setupToggleButton() {
        if (!Settings.canDrawOverlays(this)) {
            Log.w(TAG, "No overlay permission, skipping toggle button");
            return;
        }
        try {
            toggleWm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
            android.util.DisplayMetrics dm = getResources().getDisplayMetrics();

            toggleButton = new android.widget.TextView(this);
            updateToggleButtonAppearance();

            int size = (int)(40 * dm.density);
            android.view.WindowManager.LayoutParams params = new android.view.WindowManager.LayoutParams(
                size, size,
                android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                android.graphics.PixelFormat.TRANSLUCENT);
            params.gravity = android.view.Gravity.TOP | android.view.Gravity.END;
            params.x = (int)(20 * dm.density);
            params.y = (int)(120 * dm.density);

            toggleButton.setOnClickListener(v -> {
                translationEnabled = !translationEnabled;
                updateToggleButtonAppearance();
                getSharedPreferences("deepal", MODE_PRIVATE)
                    .edit().putBoolean("translation_enabled", translationEnabled).apply();
                if (!translationEnabled) {
                    mainHandler.post(() -> {
                        if (inlineManager != null) inlineManager.clearAll();
                    });
                    updateNotification("Translation OFF");
                } else {
                    updateNotification("Translation ON");
                }
            });

            toggleWm.addView(toggleButton, params);
        } catch (Exception e) {
            Log.e(TAG, "Toggle button failed: " + e.getMessage());
        }
    }

    private void updateToggleButtonAppearance() {
        if (toggleButton == null) return;
        toggleButton.setTextSize(10);
        toggleButton.setTextColor(0xFFFFFFFF);
        toggleButton.setGravity(android.view.Gravity.CENTER);
        int pad = (int)(8 * getResources().getDisplayMetrics().density);
        toggleButton.setPadding(pad, pad, pad, pad);
        if (translationEnabled) {
            toggleButton.setText("ON");
            toggleButton.setBackgroundColor(0xCC4CAF50);
        } else {
            toggleButton.setText("OFF");
            toggleButton.setBackgroundColor(0xCC999999);
        }
    }

    private void updateNotification(String text) {
        if (notificationManager == null) return;
        long now = System.currentTimeMillis();
        if (now - lastNotificationTime < 2000) return;
        lastNotificationTime = now;
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
        if (event == null || !translationEnabled) return;

        int type = event.getEventType();

        // Detect leaving target app — only clear when package actually changes
        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CharSequence pkg = event.getPackageName();
            if (pkg != null) {
                String packageName = pkg.toString();
                if (!packageName.equals(lastWindowPackage)) {
                    lastWindowPackage = packageName;
                    SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
                    boolean scanAll = prefs.getBoolean("scan_all", false);
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
        boolean scanAll = prefs.getBoolean("scan_all", false);
        int targetLang = prefs.getInt("target_lang", 0);
        boolean wordWrap = prefs.getBoolean("word_wrap", false);
        boolean darkOverlay = prefs.getBoolean("dark_overlay", false);

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
                    display, node.estimatedTextSize, node.bgColor, wordWrap, darkOverlay);
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
            // Strip HTML tags before checking
            String clean = HTML_PATTERN.matcher(s).replaceAll("").trim();
            if (isTranslatable(clean)) {
                Rect bounds = new Rect();
                node.getBoundsInScreen(bounds);
                float textSize = estimateTextSize(node);
                int bgColor = detectBackgroundColor(node);
                result.add(new TextNodeInfo(clean, bounds, textSize, bgColor));
            }
        }

        int childCount = node.getChildCount();
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collectChineseNodes(child, result, depth + 1);
                child.recycle();
            }
        }
    }

    private boolean isTranslatable(String text) {
        if (text == null || text.length() < 2 || text.length() > 200) return false;
        // Skip text with HTML-like content
        if (text.contains("<") || text.contains(">")) return false;
        // Count Chinese characters
        int chineseCount = 0;
        int totalNonSpace = 0;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (!Character.isWhitespace(c)) totalNonSpace++;
            if ((c >= 0x4E00 && c <= 0x9FFF) ||
                (c >= 0x3400 && c <= 0x4DBF) ||
                (c >= 0xF900 && c <= 0xFAFF)) {
                chineseCount++;
            }
        }
        // At least 30% of non-space chars must be Chinese
        return totalNonSpace > 0 && (chineseCount * 100 / totalNonSpace) >= 30;
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

        translateExecutor.submit(() -> {
            try {
                for (TextNodeInfo node : nodes) {
                    if (Thread.currentThread().isInterrupted()) break;
                    try {
                        String result = translateText(node.text, langCode);
                        node.translated = result;
                        translationCache.put(node.text, result);
                        translateCount++;
                    } catch (Exception e) {
                        Log.e(TAG, "Translate error: " + e.getMessage());
                    }
                }
            } finally {
                translating = false;
                final List<TextNodeInfo> batch = new ArrayList<>(nodes);
                mainHandler.post(() -> {
                    SharedPreferences p = getSharedPreferences("deepal", MODE_PRIVATE);
                    boolean ww = p.getBoolean("word_wrap", false);
                    boolean dk = p.getBoolean("dark_overlay", false);
                    for (TextNodeInfo n : batch) {
                        if (n.translated != null) {
                            inlineManager.showTranslation(
                                n.bounds.left, n.bounds.top,
                                n.bounds.width(), n.bounds.height(),
                                n.translated, n.estimatedTextSize, n.bgColor, ww, dk);
                        }
                    }
                });
                updateNotification(translateCount + " translated (cache: " + translationCache.size() + ")");
            }
        });
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
        try {
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(15000);
            conn.setRequestProperty("User-Agent", "Mozilla/5.0");

            int code = conn.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code);

            StringBuilder sb = new StringBuilder();
            try (BufferedReader r = new BufferedReader(
                    new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) sb.append(line);
            }

            try {
                org.json.JSONArray arr = new org.json.JSONArray(sb.toString());
                org.json.JSONArray first = arr.getJSONArray(0);
                StringBuilder result = new StringBuilder();
                for (int i = 0; i < first.length(); i++) {
                    org.json.JSONArray pair = first.getJSONArray(i);
                    String translated = pair.optString(0, "");
                    if (!translated.isEmpty()) result.append(translated);
                }
                if (result.length() > 0) return result.toString();
            } catch (Exception e) {
                // fall through
            }
            throw new IOException("Parse error");
        } finally {
            conn.disconnect();
        }
    }

    private String translateAlternative(String text, String langCode) throws IOException {
        String encoded = java.net.URLEncoder.encode(text, "UTF-8");
        String urlStr = "https://api.mymemory.translated.net/get?q=" + encoded +
            "&langpair=zh-CN|" + langCode;

        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        try {
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(15000);
            conn.setRequestProperty("User-Agent", "Mozilla/5.0");

            int code = conn.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code);

            StringBuilder sb = new StringBuilder();
            try (BufferedReader r = new BufferedReader(
                    new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) sb.append(line);
            }

            try {
                org.json.JSONObject obj = new org.json.JSONObject(sb.toString());
                org.json.JSONObject data = obj.getJSONObject("responseData");
                String result = data.getString("translatedText");
                if (result != null && !result.isEmpty()) return result;
            } catch (Exception e) {
                // fall through
            }
            throw new IOException("Parse error");
        } finally {
            conn.disconnect();
        }
    }

    @Override
    public void onInterrupt() {}

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        translationEnabled = false;
        if (inlineManager != null) inlineManager.clearAll();
        if (statusView != null) {
            try {
                android.view.WindowManager wm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
                wm.removeViewImmediate(statusView);
                statusView = null;
            } catch (Exception e) {
                Log.w(TAG, "onTaskRemoved: remove status overlay: " + e.getMessage());
            }
        }
        if (toggleButton != null && toggleWm != null) {
            try {
                toggleWm.removeViewImmediate(toggleButton);
                toggleButton = null;
            } catch (Exception e) {
                Log.w(TAG, "onTaskRemoved: remove toggle: " + e.getMessage());
            }
        }
        if (getSharedPreferences("deepal", MODE_PRIVATE).getBoolean("disable_acc_on_quit", false)) {
            disableSelf();
        }
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        mainHandler.removeCallbacks(retryRunnable);
        if (translateExecutor != null) translateExecutor.shutdownNow();
        if (quitReceiver != null) {
            try { unregisterReceiver(quitReceiver); } catch (Exception e) {
                Log.w(TAG, "Unregister receiver: " + e.getMessage());
            }
        }
        mainHandler.post(() -> {
            if (inlineManager != null) inlineManager.clearAll();
            if (statusView != null) {
                try {
                    android.view.WindowManager wm = (android.view.WindowManager) getSystemService(WINDOW_SERVICE);
                    wm.removeViewImmediate(statusView);
                } catch (Exception e) {
                    Log.w(TAG, "Destroy: remove status overlay: " + e.getMessage());
                }
            }
            if (toggleButton != null && toggleWm != null) {
                try { toggleWm.removeViewImmediate(toggleButton); } catch (Exception e) {
                    Log.w(TAG, "Destroy: remove toggle: " + e.getMessage());
                }
            }
        });
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
