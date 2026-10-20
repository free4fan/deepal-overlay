package com.walter.overlay;

import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

// Pure (Android-free) step-4 alignment classifier.
//
// Step-4 contract (DESIGN.md «Шаг 4»): the profile beats the pixel gates for
// ids with a definite alignment flag; the px gates are the fallback for ids
// without one. alignFor(viewId) is the SINGLE place that verdict is made, so
// every later change (removing gates A/B/D one release at a time) is audited
// against one explicit decision point instead of px-conditions hidden deep
// in computeLayout.
//
// Flag semantics (view_profiles.json, produced by tools/decompile_ids.py):
//   sl:1        start-locked — the CJK is left-aligned in EVERY layout the
//               app ships  → anchor the pill at the node's left edge.
//   g:"center"  center gravity in all layouts → center the pill on the node.
//   btn:1       dialog action button — the gate-(F) hug-stadium semantics
//               (pill == the whole button, stadium corners, est-based font);
//               deliberately NOT folded into a plain center.
//   mx:1        mixed gravity — step 3's explicit no-assert; profile must
//               not win, the px gates stay the decider.
//   g+p clash   the same id carries center gravity AND an explicit content
//               inset (g:"center" + p:dp) — contradictory for placement;
//               treated as MIXED (both flags ignored) until
//               decompile_ids.py resolves the id (step-4 debt).
//
// The classification is a pure function of the flag sets, so it is verifiable
// on the JVM without a device (tools/ProfileAlignSelfTest.java compiles
// ProfileAlign.java + the JSON parser with the stock JDK and re-checks the
// whole 7282-id profile against the audit tool's verdicts).
public final class ProfileAlign {

    // Where the pill's horizontal alignment comes from, in precedence order.
    public enum AlignSource {
        // g:"center" only (no sl, no p clash, no mx) — center on the node.
        PROFILE_CENTER,
        // sl:1 only — anchor at the node's left edge (today: isStartLocked).
        PROFILE_START,
        // btn:1 — the gate-(F) button block owns the layout.
        PROFILE_BTN,
        // mx:1 or a flag clash (sl+g, g+p) — profile flags ignored, px gates.
        MIXED,
        // no alignment flag — the px gates (A)/(B)/(C)/(D)/(E) decide.
        NONE
    }

    // One verdict per id, computed once at profile load.
    private final Map<String, AlignSource> align = new HashMap<>();

    private ProfileAlign() {}

    // Build the classifier from the profile flag sets. All four sets come
    // from loadViewProfiles(); null/empty are all legal (the app must boot
    // even when the asset is missing, the way startLockedIds already does).
    public static ProfileAlign of(Collection<String> startLocked,
                                  Collection<String> center,
                                  Collection<String> buttons,
                                  Collection<String> mixed) {
        ProfileAlign p = new ProfileAlign();
        Set<String> sl = toSet(startLocked);
        Set<String> g = toSet(center);
        Set<String> btn = toSet(buttons);
        Set<String> mx = toSet(mixed);
        Set<String> all = new HashSet<>();
        all.addAll(sl);
        all.addAll(g);
        all.addAll(btn);
        all.addAll(mx);
        for (String id : all) {
            p.align.put(id, alignFor(id, sl, g, btn, mx));
        }
        return p;
    }

    // The single alignment verdict for an id (step-4 contract). Called from
    // InlineOverlayManager.alignFor; never from the px-gate conditions
    // themselves, which stay the MIXED/NONE fallback path.
    public AlignSource alignFor(String viewId) {
        if (viewId == null) return AlignSource.NONE;
        AlignSource a = align.get(viewId);
        return a != null ? a : AlignSource.NONE;
    }

    // Precedence: mx (explicit no-assert) > sl+g clash (left vs center)
    // > button (its own gate-F semantics) > clean center > clean start.
    // Anything else falls through to NONE = the px gates.
    static AlignSource alignFor(String viewId, Set<String> sl,
                                Set<String> g, Set<String> btn,
                                Set<String> mx) {
        boolean s = viewId != null && sl.contains(viewId);
        boolean c = viewId != null && g.contains(viewId);
        boolean b = viewId != null && btn.contains(viewId);
        boolean m = viewId != null && mx.contains(viewId);
        if (m) return AlignSource.MIXED;
        if (s && c) return AlignSource.MIXED; // hard left-vs-center clash
        if (b) return AlignSource.PROFILE_BTN;
        if (c) return AlignSource.PROFILE_CENTER;
        if (s) return AlignSource.PROFILE_START;
        return AlignSource.NONE;
    }

    // The g↔p clash is decided at PARSE time (only the parser sees the p
    // flag), so clash ids are merged into the "mixed" set at load time
    // (TranslationService.loadViewProfiles). Mirror of the audit tool:
    // clean center = g, and no sl, and no p, and no mx; btn is exempt from
    // the p clash because btn ids carry g:center by step-3 design (the
    // button's own layout is centered; p there is the button's inset, not a
    // placement fact).
    public static boolean isClash(boolean sl, boolean g, boolean mx,
                                  boolean btn, boolean pFlagPresent) {
        return (sl && g)
            || (g && pFlagPresent && !mx && !btn);
    }

    public int size() {
        return align.size();
    }

    public int count(AlignSource source) {
        int n = 0;
        for (AlignSource a : align.values()) if (a == source) n++;
        return n;
    }

    private static Set<String> toSet(Collection<String> c) {
        return c != null ? new HashSet<>(c) : new HashSet<>();
    }
}
