#!/usr/bin/env bash
# Offline self-test of the step-4 alignment classifier (ProfileAlign) —
# the «явный AlignSource + alignFor» pre-frame-(1) gate. Stock JDK only:
# compiles the app's ProfileAlign.java + tools/ProfileAlignSelfTest.java
# into a scratch build dir and runs the class over the real 7282-id
# profile. No Android, no JUnit, no device.
#
# Checks (see ProfileAlignSelfTest.java): every id's verdict matches the
# step-4 reference rule, known ids (tvNegative/tvPositive/tvTopTitle/
# tv_title) classify as the documented fact, and — if the audit tool was
# run with --tsv — the Java verdicts match the audit's verdicts id-for-id.
#
# Usage:  bash tools/test_profile_align.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="$(mktemp -d /tmp/opencode/profile_align_test.XXXXXX)"
trap 'rm -rf "$OUT"' EXIT

# Regenerate the audit verdicts (TSV) so the cross-check never runs on a
# stale artifact. The audit exits 1 WHILE the documented g+p clash debt
# (43 ids, DESIGN.md step-4) is open — expect 0 or 1, fail on anything
# else. (rc must be captured from the plain command: after `if ! cmd` the
# $? is the INVERTED status — that bug silently skipped the whole test.)
if python3 tools/audit_profile_conflicts.py --tsv "$OUT/align_verdicts.tsv" \
        > /dev/null; then
    rc=0
else
    rc=$?
fi
if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
    echo "audit tool failed with exit $rc" >&2
    exit "$rc"
fi

javac -nowarn -d "$OUT" \
    app/src/main/java/com/walter/overlay/ProfileAlign.java \
    tools/ProfileAlignSelfTest.java

java -cp "$OUT" ProfileAlignSelfTest "$PWD" "$OUT/align_verdicts.tsv"
