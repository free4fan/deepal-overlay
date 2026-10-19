#!/usr/bin/env bash
# Golden capture (brief prompt.md, step 1).
#
# For each screen in the list (tools/screens.json default, or a JSON file
# arg) captures, per screen, into OUT/RUN/<screen>/:
#   a11y.xml         uiautomator dump (node bounds — the deterministic truth)
#   overlays.txt     dumpsys window (pill windows + rects + display size)
#   screenshot.png   full screen (manual check / image diff)
# Plus RUN/manifest.txt. Out dir: $OUT/$RUN (default tools/golden).
#
# Device rules (brief): never force-stop com.walter.overlay; Deepal only
# via deepal.com.cn.app/.SplashActivity; the screen with WAIT=N needs a
# manual step (dialog/screen) — the script prints it and sleeps N.
#
# Pill rects (deterministic source): overlay windows are INVISIBLE to
# uiautomator and dumpsys (no package/title), so the app itself dumps the
# active pill geometry to its private dir while the flag
# files/golden_capture exists (armed below via run-as; debug builds only —
# on a release install run-as is blocked, and the script falls back to
# "pill geometry unavailable" instead of guessing).
#
# uiautomator 'could not get idle state' + stale-file (10-18 finding):
# live Deepal screens (3D car / live map) intermittently never reach
# a11y idle, so `uiautomator dump` FAILS and does NOT overwrite the
# target file — an un-validated pull then ships a leftover tree from an
# earlier run (observed: fresh dumps on the car tab kept returning the
# byte-identical 47-node shop tree of a previous capture). The script
# therefore: wipes the remote target BEFORE each attempt (no file => no
# stale tree), treats "UI hierchary dumped to:" as the only success,
# validates good dumps against the app's own pills.json (id+text overlap
# >= 60%), restubs the uiautomator process
# (am force-stop com.android.uiautomator.stub — the "never force-stop"
# rule targets com.walter.overlay only) and retries up to 8 times with
# pacing. If nothing validates, a11y.xml is left absent and
# diff_golden.py falls back to pills.json-derived node rects.

set -uo pipefail

DEV="${DEV:-}"
if [ -z "$DEV" ]; then
  for d in $(adb devices | awk 'NR>1 && $2=="device"{print $1}'); do DEV="$d"; break; done
fi
if [ -z "$DEV" ] && [ "${ALLOW_OFFLINE:-0}" != "1" ]; then
  echo "no device; run on device or use ALLOW_OFFLINE=1 (diff only)" >&2
  exit 1
fi
echo "device: ${DEV:-<offline>}"

OUT="${OUT:-tools/golden}"
RUN="${RUN:-${RUN:-$(date +%Y%m%d_%H%M%S)}}"
# --resume mode takes <dir> as $1, not a screen list — default the list away
# before the file check so the handler below stays reachable.
case "$1" in
  --resume) LIST="tools/screens.json" ;;
  *) LIST="${1:-tools/screens.json}" ;;
esac
[ -f "$LIST" ] || { echo "screen list not found: $LIST" >&2; exit 1; }
SCREENS=$(jq -r '.[].name' "$LIST")
mkdir -p "$OUT"

PKEYS="$(adb -s "$DEV" shell pm list packages -3 2>/dev/null | grep -o 'com.walter.overlay' | head -1)"
DEBUG_OK=0
if [ "$PKEYS" = "com.walter.overlay" ] && \
   adb -s "$DEV" shell "run-as com.walter.overlay id" >/dev/null 2>&1; then
  DEBUG_OK=1
fi
echo "app: ${PKEYS:-<missing>}  golden-dump capable: ${DEBUG_OK}"

arm()   { [ "$DEBUG_OK" = "1" ] && adb -s "$DEV" shell "run-as com.walter.overlay touch files/golden_capture" >/dev/null 2>&1; }
disarm(){ [ "$DEBUG_OK" = "1" ] && adb -s "$DEV" shell "run-as com.walter.overlay rm -f files/golden_capture files/pills.json" >/dev/null 2>&1; }
pull_pills() { # $1=out dir — pull the app's pills.json (last reconcile dump)
  [ "$DEBUG_OK" = 1 ] || return 0
  adb -s "$DEV" shell "run-as com.walter.overlay cat files/pills.json" 2>/dev/null \
    | head -c 2000000 > "$1/pills.json"
  # guard against run-as error text masquerading as a capture
  [ -s "$1/pills.json" ] && head -c1 "$1/pills.json" | grep -q '^\[' || rm -f "$1/pills.json"
}

# restart the uiautomator dump stub (cleans any half-dead uiautomator
# process; both package names hit for cross-version tolerance).
restub() {
  timeout 15 adb -s "$DEV" shell "am force-stop com.android.uiautomator.stub; am force-stop com.android.uiautomator.core" >/dev/null 2>&1
  sleep 2
}

# validated uiautomator dump (used by the list loop and by --resume).
# $1=out dir $2=screen name; writes $1/a11y.xml.
#
# uiautomator 'could not get idle state' (10-18 finding): live Deepal
# screens (3D car / map) intermittently NEVER reach a11y idle, so `dump`
# FAILS SILENTLY and does NOT rewrite the target. The old script pulled
# the leftover file and shipped a tree of another screen (observed: 20+
# identical dumps of the stale shop tree). Hence: (1) the remote target is
# wiped BEFORE every attempt, so a failed attempt leaves NO file (never a
# stale one); (2) a good attempt is validated against the app's own
# pills.json (id+text overlap >= 60%) — source-independent; (3) up to 8
# attempts with pacing. diff_golden.py additionally falls back to
# pills.json-derived node rects when a11y.xml is absent or stale.
dump_a11y() { # $1=out dir $2=screen
  d="$1"; s="$2"
  local i=1 ok=0
  while [ "$i" -le 8 ]; do
    restub
    # wipe target first: on failure no file lands on /sdcard, so a pull
    # can never resurrect a stale tree
    timeout 15 adb -s "$DEV" shell rm -f /sdcard/_g.xml >/dev/null 2>&1
    timeout 60 adb -s "$DEV" shell uiautomator dump /sdcard/_g.xml \
      2>&1 | grep -q "UI hierchary dumped" || {
        echo "  a11y: dump failed ($i/8, idle/busy tree — expected on 3D screens)" >&2
        sleep 4; i=$((i+1)); continue; }
    timeout 20 adb -s "$DEV" pull /sdcard/_g.xml "$d/a11y.xml" >/dev/null 2>&1
    local nodes
    nodes=$(grep -o '<node ' "$d/a11y.xml" 2>/dev/null | wc -l)
    # overlap validation against the app-own pills.json of the SAME capture.
    # Matched by resource-id SET (pills' ids ⊆ fresh a11y ids of the same
    # screen → ≥0.6). NOT by text: the a11y tree carries the CJK source
    # while pills carry translated RU — text equality is structurally 0 and
    # a naive (id,text) check discards every good tree (10-18 finding:
    # 8 good 130-node dumps rejected while a stale 47-node tree shipped).
    local okv="no-pills"
    if [ -s "$d/pills.json" ] && command -v python3 >/dev/null; then
      okv=$(python3 - "$d/a11y.xml" "$d/pills.json" <<'PYEOF'
import json, re, sys
try:
    raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    pills = json.load(open(sys.argv[2], encoding="utf-8"))
except Exception:
    print("no-pills"); sys.exit()
ids = set(re.findall(r'resource-id="deepal[^"]*"', raw))
ids = {i.rsplit("/", 1)[-1] for i in ids}
p = [e.get("id", "") for e in pills if e.get("id")]
if not p:
    print("no-pills")
else:
    frac = sum(1 for q in p if q in ids) / len(p)
    print("ok" if frac >= 0.6 else "low-idoverlap(%.0f%%)" % (frac*100))
PYEOF
)
    fi
    if [ "$okv" = "ok" ] || [ "$okv" = "no-pills" ]; then
      ok=1; break
    fi
    echo "  a11y: $okv ($i/8): ${nodes} nodes [$(date +%H:%M:%S)]" >&2
    sleep 5; i=$((i+1))
  done
  if [ "$ok" != 1 ]; then
    echo "  a11y: WARN — no valid dump after 8 tries; a11y.xml absent (diff will use pills.json-derived nodes)" >&2
    rm -f "$d/a11y.xml"
  fi
  return 0
}

# grab one screen (used by the list loop and by --resume).
# Order matters: settle -> pills (they anchor the a11y validation) ->
# validated a11y dump -> overlays -> screenshot.
grab() { # $1=out dir $2=screen
  d="$1"; s="${2:-$1}"; s="$(basename "$s")"
  mkdir -p "$d"
  # small settle so the app's golden dump (700ms throttle) has the current pills
  sleep 1
  pull_pills "$d"
  dump_a11y "$d" "$s"
  timeout 30 adb -s "$DEV" shell dumpsys window windows > "$d/overlays.txt" 2>/dev/null
  timeout 30 adb -s "$DEV" shell screencap -p /sdcard/_g.png >/dev/null 2>&1
  adb -s "$DEV" pull /sdcard/_g.png "$d/screenshot.png" >/dev/null 2>&1
}

if [ "${1:-}" = "--resume" ]; then
  arm; grab "$2"; disarm
  echo "resumed -> $2"
  exit 0
fi

# Device rule: Deepal ONLY via SplashActivity; never force-stop com.walter.overlay.
# Bring it to the foreground, then arm the golden dump, then capture.
adb -s "$DEV" shell am start -n deepal.com.cn.app/.SplashActivity >/dev/null 2>&1
# wait for the car tab to be foreground (overlay only renders over Deepal)
for _ in $(seq 1 25); do
  f="$(timeout 10 adb -s "$DEV" shell dumpsys window 2>/dev/null | grep -m1 mCurrentFocus)"
  case "$f" in *deepal.com.cn.app*) break;; esac
  sleep 1
done
echo "foreground: ${f:-<unknown>}"
arm
trap disarm EXIT

for s in $SCREENS; do
  echo "== $s"
  case "$s" in
    dialog_keyless)
      echo "  >>> MANUAL: open the keyless-driving dialog (Бесключевое вождение) <<<<"
      sleep "${WAIT:-45}";;
    shop|explore|trip_info|notifications|settings_car|service_deepal_grid|service_acc|my_tab)
      echo "  >>> MANUAL: bring the screen '$s' forward <<<<"; sleep "${WAIT:-30}";;
    mashina_scroll)
      adb -s "$DEV" shell input swipe 480 1700 480 700 300 >/dev/null 2>&1
      sleep 2;;
    *) : ;;
  esac
  grab "$OUT/$RUN/$s"
  echo "  a11y $(wc -c < "$OUT/$RUN/$s/a11y.xml" 2>/dev/null)B, overlays $(wc -l < "$OUT/$RUN/$s/overlays.txt" 2>/dev/null)L, pills $([ -f "$OUT/$RUN/$s/pills.json" ] && echo yes || echo NO), png $(wc -c < "$OUT/$RUN/$s/screenshot.png" 2>/dev/null)B"
done

disarm
trap - EXIT

{
  echo "run=$RUN dev=${DEV:-offline} ts=$(date -u +%FT%TZ)"
  echo "apk_version=$(adb -s "$DEV" shell dumpsys package com.walter.overlay 2>/dev/null | grep -m1 versionName | tr -d ' ')"
  for s in $SCREENS; do [ -d "$OUT/$RUN/$s" ] && echo "screen=$s"; done
} > "$OUT/$RUN/manifest.txt"
echo "captured -> $OUT/$RUN  (arm flag removed)"
echo "compare: python3 tools/diff_golden.py <baseline_dir> $OUT/$RUN"
