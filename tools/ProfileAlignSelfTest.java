import com.walter.overlay.ProfileAlign;

import java.util.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

// JVM self-test for the step-4 alignment classifier (ProfileAlign).
// Compiles + runs ProfileAlign.java against the real app profile with the
// stock JDK (no Android, no JUnit, no device).
//
// Checks:
//   1. Every profile id: classifier verdict == the reference step-4 rule
//      (mx > sl+g clash > g+p clash > btn > g > sl > NONE — the same rule
//      tools/audit_profile_conflicts.py and TranslationService use).
//   2. Spot-checks against the known step-3/4 facts (tvNegative/tvPositive
//      PROFILE-BTN; tvTopTitle g+p -> MIXED; tv_title mx -> MIXED).
//   3. If tools/align_verdicts.tsv exists (audit tool --tsv output): the
//      Java verdict for every flagged id must equal the audit verdict.
//   4. Edge behavior: null / unknown id -> NONE; empty classifier -> NONE
//      (the profile-load-failure behavior).
//
// Run via:  bash tools/test_profile_align.sh
//   (it compiles ProfileAlign.java + this file into a build dir, then runs
//   the class with the repo root as arg 1).

public final class ProfileAlignSelfTest {
    private static int fails = 0;

    static void check(boolean ok, String what) {
        if (!ok) { fails++; System.out.println("FAIL: " + what); }
    }

    // ---- minimal strict JSON scanner -----------------------------------
    // The profile is machine-generated (tools/decompile_ids.py): bare
    // resource-id keys (no escapes) and values of the shape
    //   [number, {int-or-string flags}] | [number|null]
    // The scanner covers exactly those shapes (plus object/array/string/
    // number/null primitives) and refuses anything else, so a future format
    // change fails LOUDLY instead of mis-parsing silently.

    static final class P { int i; }

    static int ws(String s, P p) {
        while (p.i < s.length() && Character.isWhitespace(s.charAt(p.i))) p.i++;
        return p.i;
    }

    static String parseString(String s, P p) {
        if (p.i >= s.length() || s.charAt(p.i) != '"') err(s, p, "string");
        p.i++;
        int st = p.i;
        while (p.i < s.length() && s.charAt(p.i) != '"') {
            if (s.charAt(p.i) == '\\') err(s, p, "escape (profile ids are bare)");
            p.i++;
        }
        if (p.i >= s.length()) err(s, p, "unterminated string");
        String v = s.substring(st, p.i);
        p.i++; // closing quote
        return v;
    }

    static void expect(String s, P p, char c) {
        if (p.i >= s.length() || s.charAt(p.i) != c) err(s, p, String.valueOf(c));
        p.i++;
    }

    static void err(String s, P p, String what) {
        int line = 1;
        for (int k = 0; k < p.i; k++) if (s.charAt(k) == '\n') line++;
        throw new RuntimeException("bad json near line " + line + " (want " + what + "): "
            + s.substring(Math.max(0, p.i - 24), Math.min(s.length(), p.i + 24)));
    }

    static final class Profile {
        String id;
        final Map<String, String> flags = new LinkedHashMap<String, String>();
    }

    static void parseProfile(String json, Map<String, Profile> out) {
        P p = new P();
        ws(json, p);
        expect(json, p, '{');
        ws(json, p);
        if (json.charAt(p.i) == '}') { p.i++; }
        while (p.i < json.length() && json.charAt(p.i) != '}') {
            ws(json, p);
            String key = parseString(json, p);
            ws(json, p);
            expect(json, p, ':');
            ws(json, p);
            parseValue(json, p, key, out);
            ws(json, p);
            if (json.charAt(p.i) == ',') { p.i++; continue; }
            if (json.charAt(p.i) == '}') { p.i++; break; }
            err(json, p, "'{' or '}'");
        }
    }

    // value = [sp|null] | [sp|null, {flags}]
    static void parseValue(String s, P p, String id, Map<String, Profile> out) {
        expect(s, p, '[');
        P pp = new P(); pp.i = p.i;
        ws(s, pp);
        // sp element: number or null
        if (s.charAt(pp.i) == 'n') {
            if (!s.substring(pp.i, Math.min(s.length(), pp.i + 4)).equals("null"))
                err(s, pp, "null");
            pp.i += 4;
        } else {
            int st = pp.i;
            while (pp.i < s.length() && "0123456789+-.eE".indexOf(s.charAt(pp.i)) >= 0) pp.i++;
            if (pp.i == st) err(s, pp, "number");
        }
        ws(s, pp);
        Profile prof = new Profile();
        prof.id = id;
        if (s.charAt(pp.i) == ',') {
            pp.i++;
            ws(s, pp);
            if (s.charAt(pp.i) != '{') err(s, pp, "flag object");
            pp.i++;
            ws(s, pp);
            if (s.charAt(pp.i) != '}') {
                while (true) {
                    ws(s, pp);
                    String k = parseString(s, pp);
                    ws(s, pp);
                    expect(s, pp, ':');
                    ws(s, pp);
                    if (s.charAt(pp.i) == '"') {
                        prof.flags.put(k, parseString(s, pp));
                    } else {
                        int st = pp.i;
                        while (pp.i < s.length() && "0123456789+-.eE".indexOf(s.charAt(pp.i)) >= 0) pp.i++;
                        if (pp.i == st) err(s, pp, "flag number");
                        prof.flags.put(k, s.substring(st, pp.i)); // RAW token: "1", not "1.0"
                    }
                    ws(s, pp);
                    if (s.charAt(pp.i) == ',') { pp.i++; continue; }
                    if (s.charAt(pp.i) == '}') { pp.i++; break; }
                    err(s, pp, "'{' or '}' in flags");
                }
            } else {
                pp.i++;
            }
        }
        ws(s, pp);
        if (pp.i >= s.length() || s.charAt(pp.i) != ']') err(s, pp, "array end");
        pp.i++;
        out.put(id, prof);
        p.i = pp.i;
    }

    // The reference step-4 rule (mirror of audit_profile_conflicts.py and
    // the TranslationService load-time routing — keep the three in sync).
    // Returns the enum NAME (underscore form) for direct comparison with
    // AlignSource.name().
    static String referenceVerdict(boolean slF, boolean gF, boolean mx,
                                   boolean btnF, boolean pFlag) {
        if (mx) return "MIXED";
        if (slF && gF) return "MIXED";
        if (gF && pFlag && !btnF) return "MIXED";
        if (btnF) return "PROFILE_BTN";
        if (gF) return "PROFILE_CENTER";
        if (slF) return "PROFILE_START";
        return "NONE";
    }

    // The audit TSV uses hyphens (PROFILE-START); the enum uses underscores.
    static String auditToEnum(String audit) {
        return audit.replace('-', '_');
    }

    public static void main(String[] args) throws Exception {
        String repo = args.length > 0 ? args[0] : ".";
        String tsvArg = args.length > 1 ? args[1] : null;
        String json = new String(Files.readAllBytes(
            Paths.get(repo, "app/src/main/assets/view_profiles.json")),
            StandardCharsets.UTF_8);

        Map<String, Profile> prof = new LinkedHashMap<String, Profile>();
        parseProfile(json, prof);
        System.out.println("profile ids parsed: " + prof.size());
        check(prof.size() > 7000, "profile size sanity (expect ~7282)");

        // Build the classifier the way TranslationService does.
        Set<String> sl = new HashSet<String>(), g = new HashSet<String>(),
            btn = new HashSet<String>(), mx = new HashSet<String>();
        for (Profile pr : prof.values()) {
            boolean slF = "1".equals(pr.flags.get("sl"));
            boolean gF = "center".equals(pr.flags.get("g"));
            boolean bF = "1".equals(pr.flags.get("btn"));
            boolean mF = "1".equals(pr.flags.get("mx"));
            boolean pF = pr.flags.containsKey("p");
            if (slF) sl.add(pr.id);
            if (ProfileAlign.isClash(slF, gF, mF, bF, pF)) mx.add(pr.id);
            else if (mF) mx.add(pr.id);
            else if (bF) btn.add(pr.id);
            else if (gF) g.add(pr.id);
        }
        ProfileAlign align = ProfileAlign.of(sl, g, btn, mx);
        System.out.println("classifier: " + align.size() + " verdicts — center="
            + align.count(ProfileAlign.AlignSource.PROFILE_CENTER)
            + " start=" + align.count(ProfileAlign.AlignSource.PROFILE_START)
            + " btn=" + align.count(ProfileAlign.AlignSource.PROFILE_BTN)
            + " mixed=" + align.count(ProfileAlign.AlignSource.MIXED));

        // 1. Every id vs the reference rule.
        int mismatch = 0;
        for (Profile pr : prof.values()) {
            boolean slF = "1".equals(pr.flags.get("sl"));
            boolean gF = "center".equals(pr.flags.get("g"));
            boolean bF = "1".equals(pr.flags.get("btn"));
            boolean mF = "1".equals(pr.flags.get("mx"));
            boolean pF = pr.flags.containsKey("p");
            String want = referenceVerdict(slF, gF, mF, bF, pF);
            String got = align.alignFor(pr.id).name();
            if (!want.equals(got) && mismatch < 20)
                System.out.println("MISMATCH " + pr.id + " want=" + want + " got=" + got);
            if (!want.equals(got)) mismatch++;
        }
        check(mismatch == 0, "classification vs reference rule (" + mismatch + ")");

        // 2. Spot-checks against known step-3/4 facts.
        check(align.alignFor("tvNegative") == ProfileAlign.AlignSource.PROFILE_BTN,
            "tvNegative must be PROFILE-BTN");
        check(align.alignFor("tvPositive") == ProfileAlign.AlignSource.PROFILE_BTN,
            "tvPositive must be PROFILE-BTN");
        check(align.alignFor("tvTopTitle") == ProfileAlign.AlignSource.MIXED,
            "tvTopTitle (g=center + p=20dp) must be MIXED (documented debt)");
        check(align.alignFor("tv_title") == ProfileAlign.AlignSource.MIXED,
            "tv_title (mx=1) must be MIXED");

        // 3. Audit TSV cross-check (optional path; the runner script
        //    regenerates it into its scratch dir from the audit tool).
        Path tsv = tsvArg != null ? Paths.get(tsvArg)
            : Paths.get(repo, "tools/align_verdicts.tsv");
        if (Files.exists(tsv)) {
            List<String> lines = Files.readAllLines(tsv, StandardCharsets.UTF_8);
            int n = 0, bad = 0;
            for (int i = 1; i < lines.size(); i++) {
                String[] f = lines.get(i).split("\t", -1);
                if (f.length < 2) continue;
                n++;
                if (!align.alignFor(f[0]).name().equals(auditToEnum(f[1]))) {
                    if (bad < 10) System.out.println("TSV-MISMATCH " + f[0]
                        + " audit=" + f[1] + " java=" + align.alignFor(f[0]));
                    bad++;
                }
            }
            check(bad == 0, "audit TSV cross-check (" + bad + "/" + n + ")");
            System.out.println("audit TSV cross-check: " + (n - bad) + "/" + n + " agree");
        } else {
            System.out.println("(no tools/align_verdicts.tsv — run the audit with --tsv to cross-check)");
        }

        // 4. Edge behavior.
        check(align.alignFor(null) == ProfileAlign.AlignSource.NONE, "null id -> NONE");
        check(align.alignFor("definitely_not_an_id") == ProfileAlign.AlignSource.NONE,
            "unknown id -> NONE");
        ProfileAlign empty = ProfileAlign.of(null, null, null, null);
        check(empty.alignFor("tvTopTitle") == ProfileAlign.AlignSource.NONE,
            "empty classifier -> NONE (profile-load-failure behavior)");
        check(empty.size() == 0, "empty classifier size 0");

        if (fails == 0) {
            System.out.println("ProfileAlign self-test: PASS (" + prof.size() + " ids)");
        } else {
            System.out.println("ProfileAlign self-test: " + fails + " FAILURE(S)");
            System.exit(1);
        }
    }
}
