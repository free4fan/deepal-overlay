package com.walter.overlay;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
    private static final long[] FOLLOW_UP_SCAN_DELAYS = {400, 1200, 2500};
    private static TranslationService instance;

    private InlineOverlayManager inlineManager;
    private Handler mainHandler = new Handler(Looper.getMainLooper());
    private NotificationManager notificationManager;
    private int translateCount = 0;
    private String lastPackage = "";
    private long lastScanTime = 0;
    private String lastWindowPackage = "";
    private volatile boolean translating = false;
    private final List<TextNodeInfo> translateQueue = new ArrayList<>();
    private final Set<String> queuedTexts = new HashSet<>();
    // Access-order LRU caches, guarded by cacheLock: the executor thread and the
    // main thread both read/write, so the non-thread-safe LinkedHashMap must be
    // synchronized externally
    private final Object cacheLock = new Object();
    private final Map<String, String> cacheEn = newLruCache();
    private final Map<String, String> cacheRu = newLruCache();
    private static final int CACHE_MAX_ENTRIES = 20000;
    private static final String CACHE_FILE = "translation_cache.json";
    private Map<String, String> dictEn = new HashMap<>();
    private Map<String, String> dictRu = new HashMap<>();
    private volatile boolean dictLoaded = false;
    private boolean translationEnabled = true;
    private boolean trailingScanScheduled = false;
    private int scanEpoch = 0;
    // Last foreground package seen via TYPE_WINDOW_STATE_CHANGED. Overlay
    // placement is gated on this so a batch that was started in Deepal cannot
    // recreate pills over another app after the user has already left.
    private volatile String activePackage = "";
    private static final long WATCHDOG_MS = 3000;
    private static final long FOREIGN_WINDOW_CLEAR_DELAY_MS = 500;
    private final Runnable watchdogScan = new Runnable() {
        @Override
        public void run() {
            if (translationEnabled) scanWindow();
            mainHandler.postDelayed(this, WATCHDOG_MS);
        }
    };
    // Delayed cancellable clear: app startup/scroll emits transient foreign
    // windows (SystemUI transitions, toasts). An instant clearAll on each one
    // wiped live overlays — they reappeared only after the next successful scan
    private final Runnable foreignClearRunnable = () -> {
        if (!translationEnabled) return;
        if (inlineManager != null) inlineManager.clearAll();
    };

    private void scheduleForeignClear() {
        mainHandler.removeCallbacks(foreignClearRunnable);
        mainHandler.postDelayed(foreignClearRunnable, FOREIGN_WINDOW_CLEAR_DELAY_MS);
    }

    private void cancelForeignClear() {
        mainHandler.removeCallbacks(foreignClearRunnable);
    }
    private final Runnable trailingScan = () -> {
        trailingScanScheduled = false;
        if (translationEnabled) scanWindow();
    };
    private android.widget.TextView toggleButton;
    private android.view.WindowManager toggleWm;
    private ExecutorService translateExecutor;
    private final Runnable retryRunnable = this::retryOverlaysIfNeeded;
    private long lastNotificationTime = 0;
    private static final Pattern HTML_PATTERN = Pattern.compile("<[^>]+>");

    @Override
    public void onServiceConnected() {
        Log.i(TAG, "Service started");
        instance = this;

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
        translationEnabled = prefs.getBoolean("translation_enabled", false);

        if (translationEnabled) {
            updateNotification("Ready — open Deepal");
            setupToggleButton();
            updateToggleButtonAppearance();
        } else {
            updateNotification("Disabled");
        }

        loadDictionary();
        loadPersistentCache();
        translateExecutor = Executors.newSingleThreadExecutor();

        // Watchdog: some pages never fire accessibility events (fragments,
        // lazy-loaded content) — periodic rescan catches them
        mainHandler.postDelayed(watchdogScan, WATCHDOG_MS);

        retryOverlaysIfNeeded();
    }

    private void retryOverlaysIfNeeded() {
        if (!translationEnabled) return;
        if (!Settings.canDrawOverlays(this)) {
            mainHandler.postDelayed(retryRunnable, 2000);
            return;
        }
        if (toggleButton == null) {
            setupToggleButton();
        }
    }

    private static Map<String, String> newLruCache() {
        return new LinkedHashMap<String, String>(256, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<String, String> eldest) {
                return size() > CACHE_MAX_ENTRIES;
            }
        };
    }

    // Store under the raw form and the normalized one (when they differ) so
    // lookups hit regardless of which form the node carried
    private void cachePut(Map<String, String> cache, String k, String v) {
        synchronized (cacheLock) {
            cache.put(k, v);
            String n = normalizeForKey(k);
            if (n != null) cache.put(n, v);
        }
    }

    private String cacheGet(Map<String, String> cache, String k) {
        synchronized (cacheLock) {
            String v = cache.get(k);
            if (v == null) v = cache.get(normalizeForKey(k));
            return v;
        }
    }

    private int cacheSize(Map<String, String> cache) {
        synchronized (cacheLock) { return cache.size(); }
    }

    private void loadDictionary() {
        new Thread(() -> {
            for (int attempt = 1; attempt <= 3 && !dictLoaded; attempt++) {
                try {
                    Map<String, String> en = loadDictFromAssets("dict_zh_en.json");
                    Map<String, String> ru = loadDictFromAssets("dict_zh_ru.json");
                    dictEn = en;
                    dictRu = ru;
                    dictLoaded = true;
                    Log.i(TAG, "Dictionary loaded: EN=" + dictEn.size() + " RU=" + dictRu.size());
                    updateNotification("Dict loaded: " + dictEn.size() + " entries");
                } catch (Exception e) {
                    Log.e(TAG, "Dictionary load failed (attempt " + attempt + "/3): " + e.getMessage());
                    try { Thread.sleep(1000); } catch (InterruptedException ie) { return; }
                }
            }
        }).start();
    }

    private Map<String, String> loadDictFromAssets(String filename) throws IOException {
        Map<String, String> dict = new HashMap<>();
        try {
            JSONObject obj = new JSONObject(readAll(getAssets().open(filename)));
            java.util.Iterator<String> keys = obj.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                dict.put(key, obj.getString(key));
            }
        } catch (JSONException e) {
            throw new IOException("JSON parse error: " + e.getMessage());
        }
        return dict;
    }

    private static String readAll(InputStream in) throws IOException {
        try (in; java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream()) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private void loadPersistentCache() {
        new Thread(() -> {
            try {
                java.io.File f = new java.io.File(getFilesDir(), CACHE_FILE);
                if (!f.exists()) return;
                JSONObject root = new JSONObject(readAll(new java.io.FileInputStream(f)));
                JSONObject en = root.optJSONObject("en");
                JSONObject ru = root.optJSONObject("ru");
                synchronized (cacheLock) {
                    if (en != null) {
                        java.util.Iterator<String> keys = en.keys();
                        while (keys.hasNext()) {
                            String k = keys.next();
                            cacheEn.put(k, en.getString(k));
                        }
                    }
                    if (ru != null) {
                        java.util.Iterator<String> keys = ru.keys();
                        while (keys.hasNext()) {
                            String k = keys.next();
                            cacheRu.put(k, ru.getString(k));
                        }
                    }
                    Log.i(TAG, "Persistent cache loaded: EN=" + cacheEn.size() + " RU=" + cacheRu.size());
                }
            } catch (Exception e) {
                Log.w(TAG, "Persistent cache load failed: " + e.getMessage());
            }
        }).start();
    }

    private void savePersistentCache() {
        try {
            JSONObject enJson;
            JSONObject ruJson;
            synchronized (cacheLock) {
                enJson = new JSONObject(cacheEn);
                ruJson = new JSONObject(cacheRu);
            }
            JSONObject root = new JSONObject();
            root.put("en", enJson);
            root.put("ru", ruJson);
            java.io.File dir = getFilesDir();
            java.io.File tmp = new java.io.File(dir, CACHE_FILE + ".tmp");
            java.io.File dst = new java.io.File(dir, CACHE_FILE);
            try (java.io.FileOutputStream os = new java.io.FileOutputStream(tmp)) {
                os.write(root.toString().getBytes(StandardCharsets.UTF_8));
            }
            if (dst.exists()) dst.delete();
            if (!tmp.renameTo(dst)) {
                Log.w(TAG, "Persistent cache rename failed");
            }
        } catch (Exception e) {
            Log.w(TAG, "Persistent cache save failed: " + e.getMessage());
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
        int bgColor = translationEnabled ? 0xCC4CAF50 : 0xCC999999;
        android.graphics.drawable.GradientDrawable shape = new android.graphics.drawable.GradientDrawable();
        shape.setShape(android.graphics.drawable.GradientDrawable.RECTANGLE);
        shape.setCornerRadius(12 * getResources().getDisplayMetrics().density);
        shape.setColor(bgColor);
        toggleButton.setBackground(shape);
        toggleButton.setText(translationEnabled ? "ON" : "OFF");
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

    private String lastNotifText = "";

    private void updateNotificationOnce(String text) {
        if (text.equals(lastNotifText)) return;
        lastNotifText = text;
        updateNotification(text);
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
                    activePackage = packageName;
                    // Any foreground change invalidates in-flight API batches
                    // and scheduled follow-up scans: their bounds belong to
                    // the previous window and must not be placed elsewhere
                    scanEpoch++;

                    if (!isTargetPackage(packageName)) {
                        scheduleForeignClear();
                        return;
                    }
                    cancelForeignClear();
                    // New target window: content may render asynchronously —
                    // re-scan a few times to catch late-loaded text
                    int epoch = scanEpoch;
                    for (long delay : FOLLOW_UP_SCAN_DELAYS) {
                        mainHandler.postDelayed(() -> {
                            if (epoch != scanEpoch) return;
                            if (translationEnabled) scanWindow();
                        }, delay);
                    }
                }
            }
        }

        // Trailing debounce: the last event of a burst always triggers a scan
        long now = System.currentTimeMillis();
        if (now - lastScanTime >= DEBOUNCE_MS) {
            lastScanTime = now;
            mainHandler.removeCallbacks(trailingScan);
            trailingScanScheduled = false;
            mainHandler.post(this::scanWindow);
        } else if (!trailingScanScheduled) {
            trailingScanScheduled = true;
            mainHandler.postDelayed(trailingScan, DEBOUNCE_MS);
        }
    }

    // Whether overlays may be drawn over a window of this package
    private boolean isTargetPackage(String packageName) {
        if (packageName == null) return false;
        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        return prefs.getBoolean("scan_all", false)
            || packageName.contains("deepal")
            || packageName.contains("changan")
            || packageName.contains("cn.app");
    }

    private void scanWindow() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;

        String packageName = root.getPackageName() != null ?
            root.getPackageName().toString() : "";
        activePackage = packageName;

        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        int targetLang = prefs.getInt("target_lang", 0);
        boolean wordWrap = prefs.getBoolean("word_wrap", false);
        boolean darkOverlay = prefs.getBoolean("dark_overlay", false);

        if (!isTargetPackage(packageName)) {
            root.recycle();
            return;
        }

        boolean packageChanged = !packageName.equals(lastPackage);
        lastPackage = packageName;

        List<TextNodeInfo> chineseNodes = new ArrayList<>();
        collectChineseNodes(root, chineseNodes);
        root.recycle();

        if (chineseNodes.isEmpty()) {
            // Clear stale overlays only when the window actually changed and has
            // nothing to translate — delayed, so transient foreign windows during
            // app startup don't wipe live overlays. When there IS content,
            // reconcile() below swaps old→new atomically in one frame.
            if (packageChanged) scheduleForeignClear();
            updateNotificationOnce(packageName + ": no Chinese text");
            return;
        }
        cancelForeignClear();

        // On language change reconcile() swaps texts atomically — no clearAll
        // (cache is kept per-language)
        final Map<String, String> dict = (targetLang == 0) ? dictEn : dictRu;
        final Map<String, String> cache = (targetLang == 0) ? cacheEn : cacheRu;

        float density = getResources().getDisplayMetrics().density;

        // Two-pass lookup: pass 1 reads, pass 2 writes, so the lookups never
        // race the LRU eviction of a still-needing entry within this scan
        final String[] hits = new String[chineseNodes.size()];
        for (int i = 0; i < chineseNodes.size(); i++) {
            TextNodeInfo node = chineseNodes.get(i);
            String raw = node.text;
            String norm = normalizeForKey(raw);

            String result = dictLoaded ? dict.get(raw) : null;
            if (result == null && norm != null) result = dictLoaded ? dict.get(norm) : null;
            if (result == null) {
                result = cacheGet(cache, raw);
                if (result == null && norm != null) result = cacheGet(cache, norm);
            }
            // legacy cache/API leftovers can still hold the literal brand
            if (result != null && raw.contains("深蓝")) result = fixBrand(result, targetLang == 0 ? "en" : "ru");
            hits[i] = result;
        }
        for (int i = 0; i < chineseNodes.size(); i++) {
            TextNodeInfo node = chineseNodes.get(i);
            if (hits[i] != null) cachePut(cache, node.text, hits[i]);
        }

        final List<TextNodeInfo> toTranslate = new ArrayList<>();
        final List<InlineOverlayManager.OverlaySpec> specs = new ArrayList<>();

        for (int i = 0; i < chineseNodes.size(); i++) {
            TextNodeInfo node = chineseNodes.get(i);
            String display = hits[i] != null ? hits[i] : node.text;

            String displayNoBr = display != null ? display : "";
            boolean centered = node.bounds.width() > 0
                && node.bounds.height() < 96 * density
                && displayNoBr.length() * node.estimatedTextSize * density * 0.5f
                    <= node.bounds.width() * 0.85f
                && !displayNoBr.contains("\n");

            specs.add(new InlineOverlayManager.OverlaySpec(
                node.bounds.left + "," + node.bounds.top,
                display, node.bounds.width(), node.bounds.height(),
                node.estimatedTextSize, node.darkZone, centered));
            if (hits[i] == null) {
                toTranslate.add(node);
            }
        }

        final int epochAtScan = scanEpoch;
        mainHandler.post(() -> {
            if (!translationEnabled) return;
            // Either the foreground window changed while this reconcile was
            // posted (epoch bump on every package change) or the active
            // window is foreign now — never paint a stale window's text
            if (epochAtScan != scanEpoch) return;
            if (!isTargetPackage(activePackage)) return;
            inlineManager.reconcile(specs, wordWrap, darkOverlay);
        });

        if (!toTranslate.isEmpty()) {
            synchronized (translateQueue) {
                for (TextNodeInfo node : toTranslate) {
                    if (queuedTexts.add(node.text)) {
                        translateQueue.add(node);
                    }
                }
            }
            updateNotification("Translating " + toTranslate.size() + " new...");
            startBatchIfIdle(epochAtScan);
        }
    }

    // The embedded dictionary is keyed by the raw resource values (with HTML
    // tags). Accessibility text loses the tags on rich-text nodes, so lookup the
    // normalized form too and backfill the raw form on a hit
    private static String normalizeForKey(String s) {
        if (s == null || s.indexOf('<') < 0) return null;
        return HTML_PATTERN.matcher(s).replaceAll("").replaceAll("\\s+", " ").trim();
    }

    private boolean isToolbarId(AccessibilityNodeInfo node) {
        String id = node.getViewIdResourceName();
        if (id == null) return false;
        return id.toLowerCase().contains("toolbar") || id.toLowerCase().contains("appbar");
    }

    private void collectChineseNodes(AccessibilityNodeInfo node, List<TextNodeInfo> result) {
        collectChineseNodes(node, result, 0);
    }

    // The service's resource context reports *window* metrics (status/nav bars
    // subtracted: 1935px here), while getBoundsInScreen uses the full-display
    // coordinate space (2142px). Culling against the window height wrongly
    // pruned the bottom navigation bar (探索/服务/爱车/商城/我的 at y≈2029+).
    // Real metrics come from the display itself.
    private void realDisplaySize(int[] out) {
        try {
            android.hardware.display.DisplayManager dm =
                (android.hardware.display.DisplayManager) getSystemService(DISPLAY_SERVICE);
            if (dm != null) {
                android.view.Display disp =
                    dm.getDisplay(android.view.Display.DEFAULT_DISPLAY);
                if (disp != null) {
                    android.util.DisplayMetrics m = new android.util.DisplayMetrics();
                    disp.getRealMetrics(m);
                    out[0] = m.widthPixels;
                    out[1] = m.heightPixels;
                    return;
                }
            }
        } catch (Throwable ignored) {
        }
        android.util.DisplayMetrics m = getResources().getDisplayMetrics();
        out[0] = m.widthPixels;
        out[1] = m.heightPixels;
    }

    private void collectChineseNodes(AccessibilityNodeInfo node, List<TextNodeInfo> result, int depth) {
        int[] size = new int[2];
        realDisplaySize(size);
        collectChineseNodes(node, result, depth, size[0], size[1]);
    }

    private void collectChineseNodes(AccessibilityNodeInfo node, List<TextNodeInfo> result,
            int depth, int screenW, int screenH) {
        if (node == null || depth > 50) return;

        CharSequence text = node.getText();
        if (text != null && text.length() > 0) {
            String s = text.toString().trim();
            // Strip HTML tags before checking; single '>' (e.g. "金融试算 >") is kept
            String clean = HTML_PATTERN.matcher(s).replaceAll("").trim();
            if (isTranslatable(clean)) {
                float density = getResources().getDisplayMetrics().density;
                Rect bounds = new Rect();
                node.getBoundsInScreen(bounds);
                // Horizontally scrolling containers (the mall's tab strip,
                // ViewPagers) keep adjacent pages in the tree at off-screen
                // coordinates; their pills would poke out on both sides of the
                // current page. Nodes fully outside the screen are invisible
                // together with everything under them — skip the subtree.
                // (zero-size container bounds are ambiguous — never prune on them)
                if (bounds.width() > 0 && bounds.height() > 0
                        && (bounds.right <= 0 || bounds.left >= screenW
                            || bounds.bottom <= 0 || bounds.top >= screenH)) {
                    return;
                }
                // Pills are only built for nodes that sit fully inside the
                // screen. A node that only partly fits horizontally (a page
                // or tab sliding across the edge) is mid-animation; its pill
                // would anchor off-screen and stick out from the page edge.
                // Keep recursing either way — partially visible children may
                // settle on-screen and be picked up in the same scan.
                // Rects that are zero-sized or inverted (right<=left) are how a
                // horizontally-scrolling container reports its off-screen pages;
                // an inverted right (e.g. -960) trivially satisfies "right<=screenW"
                // and would leak off-screen nodes into the pill list, so require
                // a well-formed, positive-area rect as well.
                if (bounds.width() > 0 && bounds.height() > 0
                        && bounds.left >= 0 && bounds.right <= screenW) {
                    // Edge strip: a tab/page whose clipped node hugs the left
                    // or right screen edge and is only a sliver wide is the
                    // previous/next carousel item mid-slide; its pill would
                    // poke across the edge ("Спо…"). Legitimate wide left-edge
                    // labels (322px "Магазин «Чэюнь»") are unaffected.
                    boolean edgeStrip = bounds.width() < 120
                        && (bounds.left < 24 || bounds.right > screenW - 24);
                    // Floating bottom tab bar: content lists scroll underneath
                    // its translucent panel. Pills for that scrolled content
                    // read as dark smears behind the tab labels — only the
                    // labels themselves (short pure-CJK: 探索/服务/爱车/商城/我的)
                    // get pills in the band.
                    boolean navBand = bounds.top >= screenH - 150;
                    if (!edgeStrip && (!navBand || isTabLabel(clean))) {
                        float textSize = estimateTextSize(bounds, density);
                        boolean darkZone = isDarkZone(node, bounds, density);
                        result.add(new TextNodeInfo(clean, bounds, textSize, darkZone));
                    }
                }
            }
        }

        int childCount = node.getChildCount();
        for (int i = 0; i < childCount; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collectChineseNodes(child, result, depth + 1, screenW, screenH);
                child.recycle();
            }
        }
    }

    // Bottom tab-bar labels are 2-char pure CJK (探索/服务/爱车/商城/我的);
    // anything longer that reaches the nav band is scrolled content behind the
    // translucent panel, not a label
    private static boolean isTabLabel(String clean) {
        if (clean.length() == 0 || clean.length() > 6) return false;
        for (int i = 0; i < clean.length(); i++) {
            if (!isHan(clean.charAt(i))) return false;
        }
        return true;
    }

    // The CJK ratio is computed on the visible (tag-stripped) text so that
    // markup characters from <a>/<font> tags don't water it down below the
    // 30% threshold; raw keeps the length check (markup inflates length)
    private boolean isTranslatable(String clean) {
        if (clean == null || clean.length() < 2 || clean.length() > 200) return false;
        int chineseCount = 0;
        int totalNonSpace = 0;
        for (int i = 0; i < clean.length(); i++) {
            char c = clean.charAt(i);
            if (Character.isWhitespace(c)) continue;
            totalNonSpace++;
            if (isHan(c)) chineseCount++;
        }
        return totalNonSpace > 0 && (chineseCount * 100 / totalNonSpace) >= 30;
    }

    private static boolean isHan(char c) {
        return (c >= 0x4E00 && c <= 0x9FFF) ||
            (c >= 0x3400 && c <= 0x4DBF) ||
            (c >= 0xF900 && c <= 0xFAFF);
    }

    // An overlay reads as part of the UI (instead of a foreign box) when its
    // background blends with the surface behind the original text:
    // opaque dark over the top band / a toolbar, translucent scrim elsewhere
    private boolean isDarkZone(AccessibilityNodeInfo node, Rect bounds, float density) {
        if (bounds.top < 140 * density) return true;

        // Only check the nearest 3 parents, recycling nodes as we traverse
        AccessibilityNodeInfo parent = node.getParent();
        boolean toolbar = false;
        for (int levels = 0; parent != null && levels < 3 && !toolbar; levels++) {
            AccessibilityNodeInfo next = parent.getParent();
            toolbar = isToolbarLike(parent);
            parent.recycle();
            if (!toolbar) parent = next;
            else { recycleChain(next); parent = null; }
        }
        recycleChain(parent);

        return toolbar && bounds.top < 240 * density;
    }

    private static boolean isToolbarLike(AccessibilityNodeInfo node) {
        String viewId = node.getViewIdResourceName();
        if (viewId != null) {
            String id = viewId.toLowerCase();
            if (id.contains("toolbar") || id.contains("appbar")) return true;
        }
        CharSequence className = node.getClassName();
        if (className == null) return false;
        String cn = className.toString();
        return cn.endsWith("Toolbar") || cn.endsWith("AppBarLayout");
    }

    private static void recycleChain(AccessibilityNodeInfo node) {
        while (node != null) {
            AccessibilityNodeInfo next = node.getParent();
            node.recycle();
            node = next;
        }
    }

    private float estimateTextSize(Rect bounds, float density) {
        // A typical text line is ~1.5x the font size (leading included); 10-24sp
        float size = bounds.height() / density * (2f / 3f);
        return Math.max(10, Math.min(size, 24));
    }

    private void startBatchIfIdle() {
        startBatchIfIdle(scanEpoch);
    }

    private void startBatchIfIdle(final int epoch) {
        if (translating) return;
        final List<TextNodeInfo> batch;
        synchronized (translateQueue) {
            if (translateQueue.isEmpty()) return;
            batch = new ArrayList<>(translateQueue);
            translateQueue.clear();
            queuedTexts.clear();
        }
        translating = true;

        SharedPreferences prefs = getSharedPreferences("deepal", MODE_PRIVATE);
        int targetLang = prefs.getInt("target_lang", 0);
        final String langCode = (targetLang == 0) ? "en" : "ru";

        translateExecutor.submit(() -> {
            final Map<String, String> cache = (targetLang == 0) ? cacheEn : cacheRu;
            try {
                for (TextNodeInfo node : batch) {
                    if (Thread.currentThread().isInterrupted()) break;
                    try {
                        String result = translateText(node.text, langCode);
                        if (result != null && node.text.contains("深蓝")) {
                            result = fixBrand(result, langCode);
                        }
                        node.translated = result;
                        cachePut(cache, node.text, result);
                        translateCount++;
                    } catch (Exception e) {
                        Log.e(TAG, "Translate error: " + e.getMessage());
                    }
                }
                // LRU evicts the least-recently-used entries automatically —
                // no more full-cache reset that would drop fresh translations
            } finally {
                translating = false;
                try {
                    savePersistentCache();
                } catch (Exception e) {
                    Log.w(TAG, "Cache save error: " + e.getMessage());
                }
                final List<TextNodeInfo> done = new ArrayList<>(batch);
                mainHandler.post(() -> {
                    if (!translationEnabled) return;
                    // Scroll/package change while the request was in flight:
                    // the fixed pre-request bounds are stale, don't place them
                    if (epoch != scanEpoch) return;
                    if (!isTargetPackage(activePackage)) return;
                    SharedPreferences p = getSharedPreferences("deepal", MODE_PRIVATE);
                    boolean ww = p.getBoolean("word_wrap", false);
                    boolean dk = p.getBoolean("dark_overlay", false);
                    float density = getResources().getDisplayMetrics().density;
                    for (TextNodeInfo n : done) {
                        if (n.translated != null) {
                            boolean centered = n.bounds.width() > 0
                                && n.bounds.height() < 96 * density
                                && n.translated.length() * n.estimatedTextSize * density * 0.5f
                                    <= n.bounds.width() * 0.85f
                                && !n.translated.contains("\n");
                            inlineManager.showTranslation(
                                n.bounds.left, n.bounds.top,
                                n.bounds.width(), n.bounds.height(),
                                n.translated, n.estimatedTextSize, n.darkZone, centered, ww, dk);
                        }
                    }
                    startBatchIfIdle();
                });
                updateNotification(translateCount + " translated (cache: " + cacheSize(cache) + ")");
            }
        });
    }

    private String translateText(String text, String langCode) throws IOException {
        String out;
        try {
            out = translateGoogle(text, langCode);
        } catch (Exception e1) {
            try {
                out = translateAlternative(text, langCode);
            } catch (Exception e2) {
                throw new IOException("All APIs failed: " + e1.getMessage());
            }
        }
        // The general-purpose APIs render the brand 深蓝 literally
        // («тёмно-синий/глубокий синий/Dark/Deep Blue») in free user content,
        // where the dictionary cannot help. The dict already maps 深蓝 ->
        // Deepal, so inside this app every occurrence is the brand
        if (text.contains("深蓝") && out != null) out = fixBrand(out, langCode);
        return out;
    }

    // Matches every inflection of the literal brand renderings the generic
    // APIs produce for 深蓝 (темно-синый/темносиний/тёмно-синие/глубокий синий/
    // dark blue/deep blue). Only applied when the source text contains 深蓝,
    // where inside this app the color word is never the actual color.
    private static final java.util.regex.Pattern BRAND_RU = java.util.regex.Pattern.compile(
        "(?i)(?:т[её]мно\\s*[- ]?син[а-яё]{1,3}|глуб[оё]к[а-яё]{1,5}\\s+син[а-яё]{1,3}|dark[\\s\\-]+blue|deep[\\s\\-]+blue)");
    private static final java.util.regex.Pattern BRAND_EN = java.util.regex.Pattern.compile(
        "(?i)(?:dark[\\s\\-]+blue|deep[\\s\\-]+blue)");

    private static String fixBrand(String s, String langCode) {
        java.util.regex.Pattern p = (langCode == null || langCode.startsWith("ru"))
            ? BRAND_RU : BRAND_EN;
        java.util.regex.Matcher m = p.matcher(s);
        if (!m.find()) return s;
        return m.replaceAll("Deepal");
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
        getSharedPreferences("deepal", MODE_PRIVATE)
            .edit().putBoolean("translation_enabled", false).apply();
        if (inlineManager != null) inlineManager.clearAll();
        if (toggleButton != null && toggleWm != null) {
            try {
                toggleWm.removeViewImmediate(toggleButton);
                toggleButton = null;
            } catch (Exception e) {
                Log.w(TAG, "onTaskRemoved: remove toggle: " + e.getMessage());
            }
        }
    }

    public static void quit() {
        TranslationService s = instance;
        if (s == null) return;
        s.translationEnabled = false;
        s.getSharedPreferences("deepal", MODE_PRIVATE)
            .edit().putBoolean("translation_enabled", false).apply();
        if (s.inlineManager != null) s.inlineManager.clearAll();
        if (s.toggleButton != null && s.toggleWm != null) {
            try {
                s.toggleWm.removeViewImmediate(s.toggleButton);
                s.toggleButton = null;
            } catch (Exception e) {
                Log.w(TAG, "quit: remove toggle: " + e.getMessage());
            }
        }
        s.disableSelf();
    }

    // Called from MainActivity.onResume: opening the app is the explicit
    // "turn translation back on" action (spec v2.10.2: «включён явно —
    // открытие приложения или кнопка»). Off state survives service restarts
    // until the user opens the app again — that is intentional, not sticky.
    public static void reactivate() {
        TranslationService s = instance;
        if (s == null) return;
        if (!s.translationEnabled) {
            s.translationEnabled = true;
            s.getSharedPreferences("deepal", MODE_PRIVATE)
                .edit().putBoolean("translation_enabled", true).apply();
        }
        s.updateNotification("Ready — open Deepal");
        if (s.toggleButton == null) {
            s.setupToggleButton();
        }
        s.updateToggleButtonAppearance();
    }

    public static void disableTranslation() {
        TranslationService s = instance;
        if (s == null) return;
        s.translationEnabled = false;
        s.getSharedPreferences("deepal", MODE_PRIVATE)
            .edit().putBoolean("translation_enabled", false).apply();
        if (s.inlineManager != null) s.inlineManager.clearAll();
        if (s.toggleButton != null && s.toggleWm != null) {
            try {
                s.toggleWm.removeViewImmediate(s.toggleButton);
                s.toggleButton = null;
            } catch (Exception e) {
                Log.w(TAG, "disableTranslation: remove toggle: " + e.getMessage());
            }
        }
        // NOT calling disableSelf() — accessibility stays on
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        instance = null;
        mainHandler.removeCallbacks(retryRunnable);
        mainHandler.removeCallbacks(trailingScan);
        mainHandler.removeCallbacks(watchdogScan);
        mainHandler.removeCallbacks(foreignClearRunnable);
        trailingScanScheduled = false;
        scanEpoch++;
        if (translateExecutor != null) {
            try {
                translateExecutor.submit(this::savePersistentCache);
                translateExecutor.shutdown();
            } catch (Exception e) {
                Log.w(TAG, "Cache save on destroy: " + e.getMessage());
            }
        }
        mainHandler.post(() -> {
            if (inlineManager != null) inlineManager.clearAll();
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
        // Computed at collection time while the AccessibilityNodeInfo is still
        // valid (the node reference is not kept — it is recycled afterwards)
        boolean darkZone;

        TextNodeInfo(String text, Rect bounds, float estimatedTextSize, boolean darkZone) {
            this.text = text;
            this.bounds = bounds;
            this.estimatedTextSize = estimatedTextSize;
            this.darkZone = darkZone;
        }
    }
}
