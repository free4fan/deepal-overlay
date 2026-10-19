#!/usr/bin/env python3
"""proof_profile_nochange.py — prove a dictionary/profile-only release
cannot change overlay behavior, WITHOUT a device or a golden capture.

Background: loadViewProfiles() in TranslationService.java (see the file; it
is a ~30-line loader) reads EXACTLY two fields from view_profiles.json:
    sp  (the [0] number, or null)  -> realFontSp : Map<String,Integer>
    sl  (the [1] object's "sl")    -> startLockedIds : Set<String>
The flags g / p / fw / btn / mx are advisory — the diff model reads them, the
overlay runtime never does.

Therefore a profile/data-only release is a guaranteed no-op for pill
geometry IFF:
    (1) no EXISTING id changes its `sp` value,
    (2) no EXISTING id changes its `sl` membership,
    (3) no NEW id introduces an `sp` (would add to realFontSp),
    (4) no NEW id introduces `sl`  (would add to startLockedIds).

This script checks all four across two profile files and prints a verdict.
It also reports the full-field byte-level diff of existing ids (informational:
if an existing id's g/p/btn/mx changed, that is advisory-only and cannot move
a pill, but it is listed so you can see it deliberately).

Usage:
    python3 tools/proof_profile_nochange.py <baseline_profile.json> <new_profile.json>

Exit code:
    0  -> runtime-impacting change  = NONE  (zero behavior change, safe)
    1  -> runtime-impacting change  = YES   (WOULD change behavior; do not ship
                                             as a data-only release)
    2  -> bad usage / unreadable file

Example:
    git show HEAD:app/src/main/assets/view_profiles.json > /tmp/base.json
    python3 tools/proof_profile_nochange.py /tmp/base.json \
        app/src/main/assets/view_profiles.json
"""
import json
import sys


def sp_of(v):
    return v[0] if (len(v) > 0 and v[0] is not None) else None


def sl_of(v):
    return len(v) > 1 and isinstance(v[1], dict) and v[1].get("sl", 0) == 1


def load(fp):
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("cannot read %s: %s" % (fp, e), file=sys.stderr)
        sys.exit(2)


def main():
    if len(sys.argv) != 3:
        print("usage: proof_profile_nochange.py <baseline_profile.json> <new_profile.json>",
              file=sys.stderr)
        sys.exit(2)

    A = load(sys.argv[1])  # baseline
    B = load(sys.argv[2])  # new

    spA = {k: sp_of(v) for k, v in A.items()}
    spB = {k: sp_of(v) for k, v in B.items()}
    slA = {k for k, v in A.items() if sl_of(v)}
    slB = {k for k, v in B.items() if sl_of(v)}

    print("baseline: %d ids   new: %d ids" % (len(A), len(B)))
    print("runtime realFontSp   (sp): A=%d  B=%d" % (len(spA), len(spB)))
    print("runtime startLocked  (sl): A=%d  B=%d" % (len(slA), len(slB)))

    # (1) existing ids: sp identical?
    sp_changed = [k for k in spA if spB.get(k) != spA[k]]
    # (2) existing ids: sl membership identical?
    sl_changed = [k for k in (set(A) & set(B)) if (k in slA) != (k in slB)]
    # (3) (4) do new ids introduce sp or sl?
    new_ids = sorted(set(B) - set(A))
    new_sp = [k for k in new_ids if sp_of(B[k]) is not None]
    new_sl = [k for k in new_ids if sl_of(B[k])]

    # informational: full-field byte diff of existing ids (advisory-only)
    byte_changed = [
        k for k in (set(A) & set(B))
        if json.dumps(A[k], sort_keys=True, ensure_ascii=False)
        != json.dumps(B[k], sort_keys=True, ensure_ascii=False)
    ]

    print("\nNEW ids (added): %d" % len(new_ids))
    for k in new_ids:
        print("   %-20s sp=%s sl=%s raw=%s"
              % (k, sp_of(B[k]), sl_of(B[k]), json.dumps(B[k], ensure_ascii=False)))

    print("\nsystemic flags (runtime-relevant):")
    print("   (1) sp changed for existing ids:    %d %s" % (len(sp_changed), sp_changed[:20]))
    print("   (2) sl changed for existing ids:    %d %s" % (len(sl_changed), sl_changed[:20]))
    print("   (3) new ids carrying sp (realFontSp): %s" % new_sp)
    print("   (4) new ids carrying sl (startLocked): %s" % new_sl)
    print("\ninformational (advisory-only, does NOT move pills):")
    print("   existing ids with any field byte-changed: %d %s"
          % (len(byte_changed), byte_changed[:20]))

    runtime_impacts = bool(sp_changed or sl_changed or new_sp or new_sl)
    print("\n== VERDICT: runtime-impacting (sp/sl) change ==")
    if runtime_impacts:
        print("   YES  -> WOULD change behavior. Do not ship as data-only.")
    else:
        print("   NONE -> zero behavior change (g/p/fw/btn/mx are advisory).")
    sys.exit(1 if runtime_impacts else 0)


if __name__ == "__main__":
    main()
