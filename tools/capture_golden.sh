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
# Offline note: overlay (TYPE_APPLICATION_OVERLAY) windows usually do NOT
# appear in uiautomator dumps — diff_golden.py checks both sources and
# reports the gap explicitly instead of silently missing the pills.

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
RUN="${RUN:-$(date +%Y%m%d_%H%M%S)}"
LIST="${1:-tools/screens.json}"
[ -f "$LIST" ] || { echo "screen list not found: $LIST" >&2; exit 1; }
SCREENS=$(jq -r '.[].name' "$LIST")
mkdir -p "$OUT"

# dump one screen (used by the list loop and by --resume)
grab() { # $1=out dir
  d="$1"; mkdir -p "$d"
  timeout 45 adb -s "$DEV" shell uiautomator dump /sdcard/_g.xml >/dev/null 2>&1
  adb -s "$DEV" pull /sdcard/_g.xml "$d/a11y.xml" >/dev/null 2>&1
  timeout 30 adb -s "$DEV" shell dumpsys window windows > "$d/overlays.txt" 2>/dev/null
  timeout 30 adb -s "$DEV" shell screencap -p /sdcard/_g.png >/dev/null 2>&1
  adb -s "$DEV" pull /sdcard/_g.png "$d/screenshot.png" >/dev/null 2>&1
}

if [ "${1:-}" = "--resume" ]; then
  grab "$2"
  echo "resumed -> $2"
  exit 0
fi

for s in $SCREENS; do
  echo "== $s"
  case "$s" in
    dialog_keyless)
      echo "  >>> MANUAL: open the keyless-driving dialog (Бесключевое вождение) <<<<"
      sleep "${WAIT:-45}";;
    shop|explore|trip_info|notifications|settings_car)
      echo "  >>> MANUAL: bring the screen '$s' forward <<<<"; sleep "${WAIT:-30}";;
    mashina_scroll)
      adb -s "$DEV" shell input swipe 480 1700 480 700 300 >/dev/null 2>&1; sleep 1;;
    *) : ;;
  esac
  grab "$OUT/$RUN/$s"
  echo "  a11y $(wc -c < "$OUT/$RUN/$s/a11y.xml" 2>/dev/null)B, overlays $(wc -l < "$OUT/$RUN/$s/overlays.txt" 2>/dev/null)L, png $(wc -c < "$OUT/$RUN/$s/screenshot.png" 2>/dev/null)B"
done

{
  echo "run=$RUN dev=${DEV:-offline} ts=$(date -u +%FT%TZ)"
  echo "apk_version=$(adb -s "$DEV" shell dumpsys package com.walter.overlay 2>/dev/null | grep -m1 versionName | tr -d ' ')"
  for s in $SCREENS; do [ -d "$OUT/$RUN/$s" ] && echo "screen=$s"; done
} > "$OUT/$RUN/manifest.txt"
echo "captured -> $OUT/$RUN"
echo "compare: python3 tools/diff_golden.py <baseline_dir> $OUT/$RUN"
