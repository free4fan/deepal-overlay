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
LIST="${1:-tools/screens.json}"
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

# dump one screen (used by the list loop and by --resume)
grab() { # $1=out dir
  d="$1"; mkdir -p "$d"
  # small settle so the app's golden dump (700ms throttle) has the current pills
  sleep 1
  timeout 45 adb -s "$DEV" shell uiautomator dump /sdcard/_g.xml >/dev/null 2>&1
  adb -s "$DEV" pull /sdcard/_g.xml "$d/a11y.xml" >/dev/null 2>&1
  timeout 30 adb -s "$DEV" shell dumpsys window windows > "$d/overlays.txt" 2>/dev/null
  pull_pills "$d"
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
