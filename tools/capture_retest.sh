#!/usr/bin/env bash
# =============================================================================
# tools/capture_retest.sh — robust AUTOMATED golden capture (device A/B retest)
# =============================================================================
# Companion to tools/capture_golden.sh. That one is the BASELINE capturer: a
# fixed 11-screen list with MANUAL steps (you drive the taps/dialogs, the
# script grabs a11y + overlays + screenshot + pills.json per screen). This
# script is the forward-looking AUTOMATED retester used to verify a release:
# you hand it an APK and it (1) installs it, (2) drives Deepal through all 11
# canonical screens by itself (robust auto-nav), (3) captures the same
# per-screen artifacts + a manifest, so you can `diff_golden.py <baseline> <run>`.
#
# It encodes the hard-won device knowledge from the 10-18/10-19 W4 sessions so
# that a clean retest does not have to rediscover them:
#   1. focus: the real mCurrentFocus line is
#      deepal.com.cn.app/deepal.com.cn.app.main.MainActivity (package name
#      appears TWICE in the component path). Match exactly, or BACK-loop.
#   2. readpills() retries through the app's 700ms pills.json dump-throttle
#      write race, instead of grabbing a half-written file (-> false "0 pills").
#   3. scroll = SLOW 1:1 drags in the safe left column (x=150, ~700ms). Measured:
#      a 400px drag moves exactly ~412px, no fling overshoot, and x=150 is not
#      intercepted by clickable feed cards / banners (a fast 400ms swipe on a
#      feed opens an external photo viewer, which then owns a11y focus).
#   4. to_top() = HARD-TOP: repeat down-drags until the sentinel's cy stops
#      changing (content cannot scroll past its top) -> deterministic for both
#      sides of an A/B comparison.
#   5. ensure_main() asserts Deepal-owns-focus BEFORE every grab/tap; if an
#      intruder holds focus (gallery viewer / launcher / notification shade /
#      lock) it force-stops the intruder and/or re-launches via .SplashActivity
#      and BACK-loops to Main. A sub-screen grab (settings / notifications) uses
#      grab_sub() = grab WITHOUT ensure_main, because a BACK there would exit the
#      sub-screen.
#   6. Per-screen a11y dump is wiped-before + success-gated on "UI hierchary
#      dumped" and validated against that screen's own pills.json (resource-id
#      set overlap >= 0.6). A stale/foreign tree (e.g. a photo viewer's) is
#      dropped, never shipped.
#
# A/B usage (the intended flow):
#   bash tools/capture_retest.sh <device> <APK_A> <outA> <RUN_A> <versionName_A>
#   bash tools/capture_retest.sh <device> <APK_B> <outB> <RUN_B> <versionName_B>
#   python3 tools/diff_golden.py <outA> <outB>
# For a data-only (dictionary/profile) release, the offline proof is
# `tools/proof_profile_nochange.py <base.json> <new.json>` (exit 0 = safe, no
# golden capture needed); this script is the live retest that backs a geometry
# release or a pre-step-4 clean baseline.
#
# STATUS: v2, assembled from interactive 10-19 debugging
# (focus/read-race/scroll hard-top/sub-screen all measured live on Pixel 9 Pro
# 960x2142 @360). The full 11-screen autonomous run is the next step once the
# device is reconnected; it is expected to supersede the manual W4 runs.
#
# Device rules inherited from capture_golden.sh: Deepal ONLY via
# deepal.com.cn.app/.SplashActivity; NEVER force-stop com.walter.overlay (the
# golden dump flag files/golden_capture is armd here via run-as, DEBUG builds
# only — on a release install run-as is blocked and the dump is inert).
# =============================================================================
set -uo pipefail
A="$1"; APK="$2"; R="$3"; RID="$4"; VER="$5"
mkdir -p "$R"
S=150          # safe scroll column (left gutter of cards, x=150)

adbrw() { timeout 15 adb -s "$A" shell "run-as com.walter.overlay $1" 2>/dev/null; }
wake()  { timeout 10 adb -s "$A" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1; sleep 0.3; }

# read live pills with retry (700ms dump-throttle write race)
readpills() { # -> stdout json; "" on failure
  local raw i
  for i in 1 2 3 4; do
    raw=$(adbrw "cat files/pills.json" 2>/dev/null)
    if python3 -c "import json,sys; json.load(sys.stdin)" <<<"$raw" 2>/dev/null; then
      printf '%s' "$raw"; return 0
    fi
    sleep 0.8
  done
  printf ''
}
cy_of() { # $1=id $2=text-prefix -> int cy or ""
  readpills | python3 - "$1" "$2" <<'PY'
import json,sys
try: d=json.load(sys.stdin)
except: sys.exit()
for p in d:
    if p.get('id')==sys.argv[1] and p.get('text','').startswith(sys.argv[2]):
        n=p['node']; print(int((n[1]+n[3])/2)); sys.exit()
PY
}
pill_c() { # $1=id $2=exact text -> "cx cy" or ""
  readpills | python3 - "$1" "$2" <<'PY'
import json,sys
try: d=json.load(sys.stdin)
except: sys.exit()
for p in d:
    if p.get('id')==sys.argv[1] and p.get('text','')==sys.argv[2]:
        x,y,w,h=p['pill']; print(int(x+w/2), int(y+h/2)); sys.exit()
PY
}
# ---- scroll: slow 1:1 drags, measured 412px==412px; scale-up for micro-residual
drag() { # $1=dy(+) up-content(+/reveal-below)=finger up, (-)=finger down
  local dy=$1
  if [ "$dy" -ge 0 ]; then
    timeout 20 adb -s "$A" shell input swipe $S 1150 $S $((1150-dy)) 700 >/dev/null 2>&1
  else
    timeout 20 adb -s "$A" shell input swipe $S 500 $S $((500+(-dy))) 700 >/dev/null 2>&1
  fi
  sleep 2
}
# anchor to target cy with |d| tolerance; micro-residual gets scaled drag;
# long distances are chunked <=900px per drag (one 700ms drag of 1800px
# becomes a fling, re-introducing overshoot).
anchor() { # $1=id $2=text-prefix $3=tgt_cy $4=tol($default 10)
  local id="$1" tp="$2" tgt="$3" tol="${4:-10}" i cy d mag step
  for i in $(seq 1 24); do
    cy=$(cy_of "$id" "$tp")
    if [ -z "$cy" ]; then
      # off-screen (above current) — reveal content downward
      drag -500; continue
    fi
    d=$((tgt - cy))
    if [ "${d#-}" -le $tol ]; then echo "    anchor $id@$tp cy=$cy≈$tgt OK (iter $i)"; return 0; fi
    mag=${d#-}
    if [ "$d" -gt 0 ]; then
      # pill above target -> move content DOWN (finger down)
      if [ "$mag" -le 80 ]; then step=$(( -mag*2 - 40 )); else step=$(( -900 )); fi
    else
      if [ "$mag" -le 80 ]; then step=$(( mag*2 + 40 )); else step=$(( 900 )); fi
    fi
    drag $step
  done
  echo "    anchor $id@$tp NOT reached (cy=${cy:-?} tgt=$tgt)"; return 1
}
# hard top: repeated down-drags until the sentinel cy stops changing
to_top() { # $1=sentinel-id $2=sentinel-prefix ; stop when sentinel==top value twice
  local sid="$1" stp="$2" i cur prev="" same=0
  for i in $(seq 1 16); do
    drag -620
    cur=$(cy_of "$sid" "$stp")
    if [ -n "$cur" ]; then
      if [ "$cur" = "$prev" ]; then same=$((same+1)); else same=0; fi
      [ "$same" -ge 2 ] && { echo "    to_top done (sentinel $sid@$stp cy=$cur stable, iter $i)"; return 0; }
      prev="$cur"
    fi
  done
  echo "    to_top: sentinel never stable (last cur=${cur:-?}) — continuing at best effort"
  return 1
}

focus_line() { timeout 12 adb -s "$A" shell dumpsys window 2>/dev/null | grep -m1 mCurrentFocus; }
in_deepal_main() { focus_line | grep -q 'deepal.com.cn.app' && focus_line | grep -q 'main.MainActivity'; }
# force Deepal back to Main from any state (sub-screen / launcher / shade / viewer)
ensure_main() {
  local i
  for i in 1 2 3; do
    local f; f=$(focus_line)
    case "$f" in
      *deepal.com.cn.app*main.MainActivity*) return 0;;
      *com.simplemobiletools.gallery*|*gallery*)
        echo "    [focus] gallery open — force-stop"; adb -s "$A" shell am force-stop com.simplemobiletools.gallery.pro >/dev/null 2>&1
        break;;
      *NotificationShade*|*StatusB*|*Keyguard*|*lockscreen*)
        echo "    [focus] shade/lock in focus — dismiss"; wake
        break;;
      *) break;;
    esac
  done
  for i in $(seq 1 10); do
    in_deepal_main && return 0
    local f; f=$(focus_line)
    case "$f" in
      *deepal.com.cn.app*)
        timeout 12 adb -s "$A" shell input keyevent KEYCODE_BACK; sleep 1.5;;
      *)
        echo "    [focus] relaunch (i=$i)"; wake
        timeout 25 adb -s "$A" shell am start -n deepal.com.cn.app/.SplashActivity >/dev/null 2>&1; sleep 3;;
    esac
  done
  in_deepal_main
}

grab_sub() { # like grab() but WITHOUT ensure_main (sub-screens: BACK would exit)
  local s="$1" ci="${2:-}" ct="${3:-}"
  wake; mkdir -p "$R/$s"
  local raw; raw=$(readpills); printf '%s' "$raw" > "$R/$s/pills.json"
  [ -s "$R/$s/pills.json" ] || rm -f "$R/$s/pills.json"
  a11y_one "$s"
  timeout 25 adb -s "$A" shell dumpsys window windows > "$R/$s/overlays.txt" 2>/dev/null
  wake
  timeout 25 adb -s "$A" shell screencap -p /sdcard/_g.png >/dev/null 2>&1
  timeout 25 adb -s "$A" pull /sdcard/_g.png "$R/$s/screenshot.png" >/dev/null 2>&1
  local n a tag=""
  n=$(python3 -c "import json;print(len(json.load(open('$R/$s/pills.json'))))" 2>/dev/null || echo 0)
  a=$([ -f "$R/$s/a11y.xml" ] && grep -o '<node ' "$R/$s/a11y.xml" | wc -l || echo 0)
  if [ -n "$ci" ] && ! grep -q "\"$ci\"" "$R/$s/pills.json" 2>/dev/null; then tag="  !! NO id=$ci"; fi
  if [ -n "$ct" ] && ! grep -q "$ct" "$R/$s/pills.json" 2>/dev/null; then tag="$tag  !! NO txt=$ct"; fi
  echo "  [$s] pills=$n a11y=$a$tag"
}
a11y_one() {
  local s="$1"
  timeout 12 adb -s "$A" shell "am force-stop com.android.uiautomator.stub; am force-stop com.android.uiautomator.core" >/dev/null 2>&1
  sleep 1
  timeout 12 adb -s "$A" shell rm -f /sdcard/_g.xml >/dev/null 2>&1
  local msg; msg=$(timeout 25 adb -s "$A" shell uiautomator dump /sdcard/_g.xml 2>&1 | tail -1)
  if echo "$msg" | grep -q "UI hierchary dumped"; then
    timeout 15 adb -s "$A" pull /sdcard/_g.xml "$R/$s/a11y.xml" >/dev/null 2>&1
    python3 - "$R/$s/a11y.xml" "$R/$s/pills.json" <<'PY' >/dev/null 2>&1 && echo "    a11y kept" || { echo "    a11y dropped(stale)"; rm -f "$R/$s/a11y.xml"; }
import json,re,sys
raw=open(sys.argv[1],encoding='utf-8',errors='replace').read()
pills=json.load(open(sys.argv[2],encoding='utf-8'))
ids={i.rsplit('/',1)[-1] for i in re.findall(r'resource-id="deepal[^"]*"',raw)}
p=[e.get('id','') for e in pills if e.get('id')]
sys.exit(0 if (not p or sum(1 for q in p if q in ids)/len(p)>=0.6) else 1)
PY
  else echo "    a11y skip (busy) — pills cover"; rm -f "$R/$s/a11y.xml"; fi
}
grab() {
  local s="$1" ci="${2:-}" ct="${3:-}"
  wake; mkdir -p "$R/$s"
  ensure_main || echo "  !! ensure_main FAILED for $s"
  local raw; raw=$(readpills); printf '%s' "$raw" > "$R/$s/pills.json"
  [ -s "$R/$s/pills.json" ] || rm -f "$R/$s/pills.json"
  a11y_one "$s"
  timeout 25 adb -s "$A" shell dumpsys window windows > "$R/$s/overlays.txt" 2>/dev/null
  wake
  timeout 25 adb -s "$A" shell screencap -p /sdcard/_g.png >/dev/null 2>&1
  timeout 25 adb -s "$A" pull /sdcard/_g.png "$R/$s/screenshot.png" >/dev/null 2>&1
  local n a tag=""
  n=$(python3 -c "import json;print(len(json.load(open('$R/$s/pills.json'))))" 2>/dev/null || echo 0)
  a=$([ -f "$R/$s/a11y.xml" ] && grep -o '<node ' "$R/$s/a11y.xml" | wc -l || echo 0)
  if [ -n "$ci" ] && ! grep -q "\"$ci\"" "$R/$s/pills.json" 2>/dev/null; then tag="  !! NO id=$ci"; fi
  [ -n "$ct" ] && grep -q "$ct" "$R/$s/pills.json" 2>/dev/null || { [ -n "$ct" ] && tag="$tag  !! NO txt=$ct"; }
  echo "  [$s] pills=$n a11y=$a$tag"
}

# ============ install + boot ============
echo "== install $APK (expect $VER) on $A"
timeout 90 adb -s "$A" install -r -d -t "$APK" | tail -1
timeout 12 adb -s "$A" shell settings put system screen_off_timeout 1800000 >/dev/null 2>&1
adb -s "$A" shell am force-stop com.simplemobiletools.gallery.pro >/dev/null 2>&1
wake
timeout 25 adb -s "$A" shell am start -n deepal.com.cn.app/.SplashActivity >/dev/null 2>&1
ensure_main || echo "!! boot ensure_main failed"
echo "focus: $(focus_line)"
INVER=$(timeout 15 adb -s "$A" shell dumpsys package com.walter.overlay 2>/dev/null | grep -m1 versionName | tr -d ' ')
echo "device: $INVER"
[ "$INVER" = "$VER" ] || { echo "  !! FATAL: version mismatch, aborting"; exit 2; }
sleep 3
EN=$(adbrw "cat shared_prefs/deepal.xml" 2>/dev/null | grep -o 'translation_enabled[^\n]*')
echo "prefs: $EN"
grep -q 'value="true"' <<<"$EN" || { echo "  !! translation_enabled OFF — stopping (turn it ON in device UI)"; exit 3; }
# Mashina tab
ensure_main
readpills | grep -q "Моя машина" 2>/dev/null || { timeout 12 adb -s "$A" shell input tap 480 2052; sleep 4; }
adbrw "touch files/golden_capture" >/dev/null 2>&1
sleep 2
ensure_main
to_top tv_main_name "Моя"
echo "start pills=$(readpills | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null)"

# 1 mashina_top (hard top)
grab mashina_top tv_main_name "Моя машина"

# 2 mashina_scroll (canonical: «Обзор поездки» cy=596)
anchor tvReportTitle "Обзор" 596
grab mashina_scroll tvReportTitle "Обзор поездки"

# 3 trip_info (same canonical state — trip card visible, not opened)
grab trip_info tvReportTitle "Обзор поездки"

# 4 dialog_keyless
for att in 1 2 3; do
  ensure_main
  DC=$(pill_c tv_main_menu_name "Вождение без ключа")
  if [ -z "$DC" ]; then echo "   tile not visible (att $att) — reveal below"; drag 450; continue; fi
  read TX TY <<<"$DC"; echo "   tap tile @ $TX $TY (att $att)"; wake
  timeout 12 adb -s "$A" shell input tap $TX $TY
  ok=""; for i in 1 2 3 4 5 6; do sleep 1; readpills | grep -q "Отмена" 2>/dev/null && { ok=1; break; }; done
  [ -n "$ok" ] && { echo "   dialog OPEN"; break; }
  echo "   dialog not open (att $att) — BACK + retry"
  ensure_main
  timeout 12 adb -s "$A" shell input keyevent KEYCODE_BACK; sleep 1
done
if readpills | grep -q '"tvNegative"' && readpills | grep -q "Отмена"; then
  grab dialog_keyless tvNegative "Отмена"
else
  echo "  [dialog_keyless] FAILED to open dialog"
fi
readpills >/dev/null 2>&1 || true
CC=$(pill_c tvNegative "Отмена")
if [ -n "$CC" ]; then read TX TY <<<"$CC"; wake; timeout 12 adb -s "$A" shell input tap $TX $TY; else timeout 12 adb -s "$A" shell input tap 283 1357; fi
sleep 2; ensure_main

# 5 service_deepal_grid (canonical: «Обзор поездки» cy=107 — deeper scroll)
anchor tvReportTitle "Обзор" 107
grab service_deepal_grid item_help_center_tv "Concierge"

# 6 service_acc (Сервис tab -> top -> «Зарядка» section title cy=78)
ensure_main
wake; timeout 12 adb -s "$A" shell input tap 280 2052; sleep 5
to_top tv_charging_title "Зарядка"
anchor tv_charging_title "Зарядка" 78
grab service_acc tv_entry_name "Дом. зарядка"

# 7 my_tab (Мой tab -> hard top)
ensure_main
wake; timeout 12 adb -s "$A" shell input tap 864 2052; sleep 5
to_top txt_user_name "Властный"
grab my_tab txt_user_name ""

# 8 settings_car (Машina -> gear drawer -> vehicle settings row)
ensure_main
wake; timeout 12 adb -s "$A" shell input tap 480 2052; sleep 4
to_top tv_main_name "Моя"
wake; timeout 12 adb -s "$A" shell input tap 878 232; sleep 2
for rx in 801 660 560; do
  wake; timeout 12 adb -s "$A" shell input tap $rx 499; sleep 4
  if readpills | grep -qi "настройки автомобиля" 2>/dev/null; then echo "   settings opened @x$rx"; break; fi
  ensure_main
  timeout 12 adb -s "$A" shell input keyevent KEYCODE_BACK; sleep 1
done
# settings page is a sub-screen: ensure_main would BACK it away -> grab_sub
grab_sub settings_car tvTopTitle "автомобиля"
timeout 12 adb -s "$A" shell input keyevent KEYCODE_BACK; sleep 3
ensure_main

# 9 notifications (bell — sub-screen; grab_sub without ensure_main)
ensure_main
wake; timeout 12 adb -s "$A" shell input tap 765 235; sleep 6
if readpills | grep -q 'titleTv' 2>/dev/null; then
  grab_sub notifications titleTv ""
else
  echo "  [notifications] titleTv not seen — grabbing anyway"
  grab_sub notifications "" ""
fi
timeout 12 adb -s "$A" shell input keyevent KEYCODE_BACK; sleep 3
ensure_main

# 10 explore (Обзор tab -> hard top)
wake; timeout 12 adb -s "$A" shell input tap 96 2052; sleep 6
to_top tab_text "Рекоменд"
grab explore banner_title ""

# 11 shop (Магазин tab -> hard top)
wake; timeout 12 adb -s "$A" shell input tap 672 2052; sleep 6
to_top title "Магазин"
grab shop title "Магазин"

adbrw "rm -f files/golden_capture files/pills.json"
timeout 12 adb -s "$A" shell settings delete system screen_off_timeout >/dev/null 2>&1
{
  echo "run=$RID dev=$A ts=$(date -u +%FT%TZ)"
  echo "apk_apk=$(basename "$APK") apk_md5=$(md5sum "$APK" | cut -d' ' -f1)"
  echo "apk_version=$VER"
  for s in mashina_top mashina_scroll trip_info dialog_keyless service_deepal_grid service_acc my_tab settings_car notifications explore shop; do
    [ -d "$R/$s" ] && echo "screen=$s"
  done
} > "$R/manifest.txt"
rm -f "$R/_live.json"
echo "capture complete -> $R"
