#!/usr/bin/env bash
# =============================================================================
# tools/golden_interactive.sh — HYBRID golden capture (user drives navigation)
# =============================================================================
# Why it exists: the autonomous driver (capture_retest.sh) degraded in 4 of
# 4 runs on a LIVE user phone (notification shade, live rotating content,
# focus flaps, blind hardcoded navigation — W4-A/B/C, 10-19/20). Here the
# USER drives the navigation (they know the app and hold the device), and the
# script ONLY takes read-only snapshots: pills (run-as runtime overlay dump),
# the validated a11y tree (quote-fixed validator; rejected dumps are KEPT as
# a11y.rejected.* for diagnosis, not deleted), an overlays.txt dumpsys slice
# and a screenshot (with a black-screen check). The single input event it may
# ever send is KEYCODE_WAKEUP when the display is OFF (a black screenshot is
# worthless); it never scrolls, never taps, never BACKs.
#
# Usage:
#   bash tools/golden_interactive.sh list
#   bash tools/golden_interactive.sh start  <device> <outdir>
#   bash tools/golden_interactive.sh grab   <device> <outdir> <screen>
#   bash tools/golden_interactive.sh finish <device> <outdir> [runid]
#
# Requirements: DEBUG overlay build (run-as for pills), translation ON
# (pref translation_enabled=true), Deepal navigated to the target state by
# the user and NOT scrolling at the moment of grab.
#
# The per-screen set is the canonical 11 of capture_retest.sh so output dirs
# are directly diff-able with tools/diff_golden.py against any other run.
# =============================================================================
set -uo pipefail

SCREENS="mashina_top mashina_scroll trip_info dialog_keyless service_deepal_grid service_acc my_tab settings_car notifications explore shop"

A=""
R=""
adbrw() { timeout 15 adb -s "$A" shell "run-as com.walter.overlay $1" 2>/dev/null; }

readpills() { # -> stdout json; "" on failure (v3.2: -c form, pipe IS stdin)
  local raw i
  for i in 1 2 3 4; do
    raw=$(adbrw "cat files/pills.json" 2>/dev/null)
    if python3 -c 'import json,sys; json.load(sys.stdin)' <<<"$raw" 2>/dev/null; then
      printf '%s' "$raw"; return 0
    fi
    sleep 0.8
  done
  printf ''
}

# wake the display if it is off (ONLY input event this script may ever send;
# a black screenshot is worthless and was exactly the W4-C my_tab failure)
wake_if_off() {
  local st
  st=$(timeout 10 adb -s "$A" shell dumpsys power 2>/dev/null | grep -m1 'Display Power:' | grep -o 'state:[A-Z]*' | cut -d: -f2)
  if [ "$st" = "OFF" ]; then
    echo "    [display off] -> KEYCODE_WAKEUP (only input event this tool sends)"
    timeout 10 adb -s "$A" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
    sleep 1
  fi
}

a11y_dump() { # $1=screen ; dumps and validates; keeps OR saves a11y.rejected
  local s="$1" att msg
  for att in 1 2 3; do
    wake_if_off
    timeout 12 adb -s "$A" shell "am force-stop com.android.uiautomator.stub; am force-stop com.android.uiautomator.core" >/dev/null 2>&1
    sleep 1
    timeout 12 adb -s "$A" shell rm -f /sdcard/_g.xml >/dev/null 2>&1
    msg=$(timeout 25 adb -s "$A" shell uiautomator dump /sdcard/_g.xml 2>&1 | tail -1)
    if ! echo "$msg" | grep -q "UI hierchary dumped"; then
      echo "    a11y busy (att $att) — retrying"
      sleep 2; continue
    fi
    timeout 15 adb -s "$A" pull /sdcard/_g.xml "$R/$s/a11y.xml" >/dev/null 2>&1
    # validator (v3.2): capture group WITHOUT the closing quote; the dump is
    # foreign only when its deepal resource-id set overlaps <60% of this
    # screen's own pills.
    if python3 - "$R/$s/a11y.xml" "$R/$s/pills.json" <<'PY' >/dev/null 2>&1
import json,re,sys
raw=open(sys.argv[1],encoding='utf-8',errors='replace').read()
pills=json.load(open(sys.argv[2],encoding='utf-8'))
ids={i.rsplit('/',1)[-1] for i in re.findall(r'resource-id="(deepal[^"]*)"',raw)}
p=[e.get('id','') for e in pills if e.get('id')]
sys.exit(0 if (not p or sum(1 for q in p if q in ids)/len(p)>=0.6) else 1)
PY
    then echo "    a11y kept (att $att)"; return 0
    else
      echo "    a11y rejected (att $att): tree/pills id-overlap < 0.6 — saved as a11y.rejected.att$att.xml"
      mv -f "$R/$s/a11y.xml" "$R/$s/a11y.rejected.att$att.xml" 2>/dev/null || true
      sleep 1
    fi
  done
  return 1
}

shot() { # $1=screen ; screencap + black check; -> echo "ok|BLACK"
  local s="$1"
  wake_if_off
  timeout 25 adb -s "$A" shell screencap -p /sdcard/_g.png >/dev/null 2>&1
  timeout 25 adb -s "$A" pull /sdcard/_g.png "$R/$s/screenshot.png" >/dev/null 2>&1
  if python3 - "$R/$s/screenshot.png" <<'PY' 2>/dev/null
import sys
from PIL import Image
im=Image.open(sys.argv[1]).convert('L')
sys.exit(0 if max(im.getdata()) < 40 else 1)
PY
  then echo "BLACK"
  else echo "ok"
  fi
}

cmd_list() {
  cat <<'EOF'
The canonical 11 (state = what the user must navigate to before 'grab'):
   1 mashina_top        «Машина» вкладка, скролл до САМОГО верха («Моя машина» + статус сверху)
   2 mashina_scroll     «Машина», скролл вниз так, чтобы блок «Обзор поездки» был виден посреди экрана
   3 trip_info          «Машина», карточка «Обзор поездки» видна, НЕ открыта
   4 dialog_keyless     «Машина», тап по «Вождение без ключа» — диалог ОТКРЫТ («Отмена»/OK видны). После снимка диалог закрыть.
   5 service_deepal_grid«Машина», скролл до сетки сервисов (плитки «Concierge»/«Центр помощи»)
   6 service_acc        вкладка «Сервис», секция «Зарядка» видна (плитка «Дом. зарядка»)
   7 my_tab             вкладка «Мой», верх (карточка профиля с именем)
   8 settings_car       «Машина» → шестерня сверху → страница «Настройки автомобиля»
   9 notifications      «Машина» → колокольчик сверху справа → страница уведомлений
  10 explore            вкладка «Обзор», верх (лента)
  11 shop               вкладка «Магазин», верх
EOF
}

cmd_start() {
  A="$1"; R="$2"
  [ -n "$A" ] && [ -n "$R" ] || { echo "usage: $0 start <device> <outdir>"; exit 64; }
  mkdir -p "$R"
  echo "== pre-checks on $A =="
  local INVER
  INVER=$(timeout 15 adb -s "$A" shell dumpsys package com.walter.overlay 2>/dev/null | grep -m1 versionName | tr -d ' ')
  echo "device overlay: $INVER ${INVER:+(keep this version steady through the whole run)}"
  if ! timeout 8 adb -s "$A" shell "run-as com.walter.overlay id" >/dev/null 2>&1; then
    echo "  !! FATAL: run-as blocked — this is a RELEASE install. Install the debug build (same version)."
    exit 4
  fi
  local EN
  EN=$(adbrw "cat shared_prefs/deepal.xml" 2>/dev/null | grep -o 'translation_enabled[^\n]*')
  echo "prefs: $EN"
  grep -q 'value="true"' <<<"$EN" || { echo "  !! translation_enabled OFF — open Deepal Translate app on the device to activate. (exit 3)"; exit 3; }
  echo "liveness probe: arm + wait for a fresh pills.json write (no input events)..."
  adbrw "rm -f files/pills.json files/golden_capture" >/dev/null 2>&1
  adbrw "touch files/golden_capture" >/dev/null 2>&1
  local LIVE=0 k
  for k in $(seq 1 10); do
    sleep 1.5
    if adbrw "cat files/pills.json" 2>/dev/null | grep -q '"id"'; then LIVE=1; break; fi
  done
  if [ "$LIVE" != "1" ]; then
    adbrw "rm -f files/golden_capture" >/dev/null 2>&1
    echo "  !! FATAL: service not reconciling (no pills.json while armed)."
    echo "      On a fresh reinstall the accessibility service can end up UNBOUND."
    echo "      Fix: Settings > Accessibility — make sure 'Deepal Translate' (com.walter.overlay)"
    echo "      is enabled there, or just open the Deepal Translate app and re-enable translation."
    exit 4
  fi
  echo "liveness OK. golden flag is ARMED — start navigating."
}

cmd_grab() {
  A="$1"; R="$2"; local s="${3:-}"
  [ -n "$A" ] && [ -n "$R" ] && [ -n "$s" ] || { echo "usage: $0 grab <device> <outdir> <screen>"; exit 64; }
  echo "== grab: $s =="
  mkdir -p "$R/$s"
  wake_if_off
  local raw
  raw=$(readpills); printf '%s' "$raw" > "$R/$s/pills.json"
  [ -s "$R/$s/pills.json" ] || rm -f "$R/$s/pills.json"
  local n
  n=$(python3 -c "import json;print(len(json.load(open('$R/$s/pills.json'))))" 2>/dev/null || echo 0)
  if [ "$n" = "0" ]; then
    echo "  !! pills=0 — flag disarmed? service stopped? nothing to validate against"
  fi
  a11y_dump "$s"
  timeout 25 adb -s "$A" shell dumpsys window windows > "$R/$s/overlays.txt" 2>/dev/null
  local SH
  SH=$(shot "$s")
  local a
  a=$([ -f "$R/$s/a11y.xml" ] && grep -o '<node ' "$R/$s/a11y.xml" | wc -l || echo 0)
  local tag=""
  local rej
  rej=$(ls "$R/$s"/a11y.rejected.* 2>/dev/null | wc -l)
  [ "$rej" -gt 0 ] && tag="$tag a11y-rejected:$rej"
  echo "  [$s] pills=$n a11y=$a shot=$SH$tag"
  [ "$SH" = "BLACK" ] && echo "  !! screenshot is BLACK — display was off/dim; re-run grab for this screen with the backlit-on."
}

cmd_finish() {
  A="$1"; R="$2"; local RID="${3:-interactive}"
  adbrw "rm -f files/golden_capture files/pills.json" >/dev/null 2>&1
  local INVER
  INVER=$(timeout 15 adb -s "$A" shell dumpsys package com.walter.overlay 2>/dev/null | grep -m1 versionName | tr -d ' ')
  {
    echo "run=$RID dev=$A ts=$(date -u +%FT%TZ)"
    echo "overlay=$INVER mode=interactive"
    for s in $SCREENS; do
      if [ -d "$R/$s" ]; then
        local n a sh
        n=$(python3 -c "import json;print(len(json.load(open('$R/$s/pills.json'))))" 2>/dev/null || echo 0)
        a=$([ -f "$R/$s/a11y.xml" ] && grep -o '<node ' "$R/$s/a11y.xml" | wc -l || echo 0)
        sh=$([ -f "$R/$s/screenshot.png" ] && stat -c%s "$R/$s/screenshot.png" || echo 0)
        echo "screen=$s pills=$n a11y=$a shot=$sh"
      else
        echo "screen=$s MISSING"
      fi
    done
  } > "$R/manifest.txt"
  cat "$R/manifest.txt"
  echo "interactive capture complete -> $R"
}

main() {
  local cmd="${1:-list}"
  shift || true
  # wireless adb ports CHANGE on every reconnect (known session rule): if the
  # given port is gone and exactly one device is attached, resolve to it.
  if [ "$cmd" != "list" ] && [ -n "${1:-}" ]; then
    if ! timeout 8 adb -s "$1" shell true >/dev/null 2>&1; then
      local only
      only=$(timeout 8 adb devices 2>/dev/null | awk 'NR>1 && $2=="device"{print $1}' | sed -n '$p')
      if [ -n "$only" ] && [ "$only" != "$1" ]; then
        echo "  [device] '$1' not connected — using $only (the only attached device)" >&2
        set -- "$only" "$@"
      fi
    fi
  fi
  case "$cmd" in
  list)   cmd_list ;;
  start)  cmd_start "$@" ;;
  grab)   cmd_grab "$@" ;;
  finish) cmd_finish "$@" ;;
  *) echo "unknown command: $cmd (list|start|grab|finish)"; exit 64;;
esac
}
main "$@"
