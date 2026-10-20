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
# STATUS: v3 (10-20) — fixes the three concrete root-causes found in the
# W4-A (10-19) and W4-B (10-20) degraded runs, where the NotificationShade
# held focus and absorbed every gesture:
#   (a) shade_ensure_closed() — closes the notification shade/lock via
#       KEYCODE_BACK (which reaches the shade, not Deepal) and is wired into
#       drag() (the single chokepoint for every scroll gesture) and
#       a11y_one() (each dump retry); the W4 runs only re-checked focus at
#       grab time, so a shade that opened mid-run ate the entire scroll loop.
#   (b) focus_ok() / anchor() / to_top() — a read that comes up empty now
#       distinguishes "off-screen" (drag) from "window not usable" (focus
#       can't be established -> ensure_main, then ABORT after 3 strikes
#       instead of burning 24 loops at nothing; W4-B sat in the empty-read
#       loop for all 10 screens).
#   (c) a11y_one() gets the shade-close + 3 attempts (was a single attempt),
#       so a one-off wrong-tree dump recovers instead of shipping a11y ABSENT.
#   (d) liveness probe at boot: arm the golden flag over the Mashina screen
#       and wait for a real pills.json write before committing to the 20-min
#       run. On failure it HEALS the W4-B precondition (fresh reinstall left
#       the accessibility service UNBOUND, Binding services: {}) with a
#       force-stop -> overlay -> Deepal focus-shift cycle, and still fails
#       fast (exit 4) with the precise cause: unbound service vs RELEASE
#       build (run-as blocked -> the probe is the only way to know run-as
#       died, since adbrw just returns empty).
# v2 (10-19): focus/read-race/scroll hard-top/sub-screen, all measured live
# on Pixel 9 Pro 960x2142 @360 (400px drag -> 412px content, no fling).
#
# Device rules inherited from capture_golden.sh: Deepal ONLY via
# deepal.com.cn.app/.SplashActivity; NEVER force-stop com.walter.overlay
# DURING the sweep (the golden dump flag files/golden_capture is armed here
# via run-as, DEBUG builds only — on a release install run-as is blocked and
# the dump is inert). One documented exception: the pre-run liveness healing
# cycle (before any arm/capture) force-stops the overlay ONCE to force AMS to
# rebind an accessibility service left unbound by a fresh reinstall; it is
# gated by the LIVE flag (runs only if the probe is failing) and the probe
# itself is the safety net — if healing doesn't restore reconciliation, the
# run aborts before consuming the sweep.
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
  # shade at the top EATS the swipe (W4-A/W4-B root cause): the single
  # chokepoint for every scroll gesture, so close it right before each one.
  shade_ensure_closed >/dev/null 2>&1
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
      # off-screen (above current) — reveal content downward. Guard against the
      # W4 failure: if Deepal isn't ownable at all, dragging forever is useless —
      # say so and stop after 3 such iterations.
      if ! focus_ok; then
        if [ "$i" -ge 3 ]; then
          echo "    anchor $id@$tp ABORTED: deepal window not usable (focus=$(focus_line | grep -o 'Window{[^}]*}') after $i reads)"
          return 1
        fi
        ensure_main; drag -500; continue
      fi
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
  local sid="$1" stp="$2" i cur prev="" same=0 bad=0
  for i in $(seq 1 16); do
    drag -620
    cur=$(cy_of "$sid" "$stp")
    if [ -n "$cur" ]; then
      if [ "$cur" = "$prev" ]; then same=$((same+1)); else same=0; fi
      [ "$same" -ge 2 ] && { echo "    to_top done (sentinel $sid@$stp cy=$cur stable, iter $i)"; return 0; }
      prev="$cur"
    else
      # W4-B mode: window not usable -> the sentinel can never be read
      if ! focus_ok; then
        bad=$((bad+1))
        ensure_main
        if [ "$bad" -ge 3 ]; then
          echo "    to_top ABORTED: deepal window not usable (focus=$(focus_line | grep -o 'Window{[^}]*}')) after $i drags"
          return 1
        fi
      fi
    fi
  done
  echo "    to_top: sentinel never stable (last cur=${cur:-?}) — continuing at best effort"
  return 1
}

focus_line() { timeout 12 adb -s "$A" shell dumpsys window 2>/dev/null | grep -m1 mCurrentFocus; }
in_deepal_main() { focus_line | grep -q 'deepal.com.cn.app' && focus_line | grep -q 'main.MainActivity'; }
# True only when Deepal Main is focused AND the window tree actually yields the
# app's nodes (an empty/degraded dumpsys — the W4-B "sentinel never stable"
# case — fails this even if the focus text looks right).
focus_ok() {
  focus_line | grep -q 'deepal.com.cn.app' \
    && timeout 15 adb -s "$A" shell dumpsys window windows 2>/dev/null \
         | grep -q 'deepal.com.cn.app.main.MainActivity'
}
# Close the notification shade / quick-settings / lockscreen if it sits on top
# (Focus=NotificationShade ABSORBS every input swipe — the W4-A/W4-B root cause,
# 10-19/10-20: the driver dragged the page for nothing, anchors never saw any
# content move, and uiautomator dumped the shade's tree). KEYCODE_BACK while
# the shade owns focus closes the shade, not the app. Patterns are kept NARROW
# (only the observed systemui/lock tokens) so a BACK is never fired for an
# app window (which would pop a dialog / sub-screen).
shade_ensure_closed() {
  local f; f=$(focus_line)
  case "$f" in
    *NotificationShade*|*Keyguard*|*lockscreen*|*LockScreen*|*com.android.keyguard*)
      timeout 10 adb -s "$A" shell input keyevent KEYCODE_BACK >/dev/null 2>&1
      sleep 0.8
      f=$(focus_line)
      case "$f" in
        *NotificationShade*|*Keyguard*|*lockscreen*|*com.android.keyguard*)
          echo "    [shade] still open — wake + BACK again"
          wake
          timeout 10 adb -s "$A" shell input keyevent KEYCODE_BACK >/dev/null 2>&1
          sleep 0.8;;
      esac
      return 0;;
  esac
  return 0
}
# force Deepal back to Main from any state (sub-screen / launcher / shade / viewer)
ensure_main() {
  local i
  shade_ensure_closed
  for i in 1 2 3; do
    local f; f=$(focus_line)
    case "$f" in
      *deepal.com.cn.app*main.MainActivity*) return 0;;
      *com.simplemobiletools.gallery*|*gallery*)
        echo "    [focus] gallery open — force-stop"; adb -s "$A" shell am force-stop com.simplemobiletools.gallery.pro >/dev/null 2>&1
        break;;
      *NotificationShade*|*Keyguard*|*lockscreen*)
        echo "    [focus] shade/lock in focus — dismiss"; wake
        break;;
      *) break;;
    esac
  done
  for i in $(seq 1 10); do
    in_deepal_main && return 0
    local f; f=$(focus_line)
    case "$f" in
      *SplashActivity*)
        # transition in flight (the driver just launched it via Splash):
        # BACK would CANCEL the transition and force a relaunch loop (this is
        # exactly what the W4-C boot did — 5 [focus] relaunch lines before
        # converging). Wait for MainActivity instead.
        sleep 3;;
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
  local s="$1" att msg
  for att in 1 2 3; do
    shade_ensure_closed
    wake
    timeout 12 adb -s "$A" shell "am force-stop com.android.uiautomator.stub; am force-stop com.android.uiautomator.core" >/dev/null 2>&1
    sleep 1
    timeout 12 adb -s "$A" shell rm -f /sdcard/_g.xml >/dev/null 2>&1
    msg=$(timeout 25 adb -s "$A" shell uiautomator dump /sdcard/_g.xml 2>&1 | tail -1)
    if ! echo "$msg" | grep -q "UI hierchary dumped"; then
      echo "    a11y skip (busy, att $att) — pills cover"
      sleep 2; continue
    fi
    timeout 15 adb -s "$A" pull /sdcard/_g.xml "$R/$s/a11y.xml" >/dev/null 2>&1
    if python3 - "$R/$s/a11y.xml" "$R/$s/pills.json" <<'PY' >/dev/null 2>&1
import json,re,sys
raw=open(sys.argv[1],encoding='utf-8',errors='replace').read()
pills=json.load(open(sys.argv[2],encoding='utf-8'))
ids={i.rsplit('/',1)[-1] for i in re.findall(r'resource-id="deepal[^"]*"',raw)}
p=[e.get('id','') for e in pills if e.get('id')]
sys.exit(0 if (not p or sum(1 for q in p if q in ids)/len(p)>=0.6) else 1)
PY
    then echo "    a11y kept (att $att)"; return 0
    else
      echo "    a11y dropped(stale) att $att (foreign tree — e.g. shade)"
      rm -f "$R/$s/a11y.xml"; ensure_main; sleep 2
    fi
  done
  rm -f "$R/$s/a11y.xml"
  return 0
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
PREV_OFF_TIMEOUT=$(timeout 8 adb -s "$A" shell settings get system screen_off_timeout 2>/dev/null | tr -d '[:space:]')
timeout 12 adb -s "$A" shell settings put system screen_off_timeout 1800000 >/dev/null 2>&1
# restore the user's screen-off timeout on ANY exit, including the FATAL
# paths that return before the final disarm section (the W4-C exit-2 run
# left the device at 1800000 because it died before the explicit delete).
restore_timeout() { timeout 12 adb -s "$A" shell settings delete system screen_off_timeout >/dev/null 2>&1; }
trap restore_timeout EXIT
adb -s "$A" shell am force-stop com.simplemobiletools.gallery.pro >/dev/null 2>&1
wake
timeout 25 adb -s "$A" shell am start -n deepal.com.cn.app/.SplashActivity >/dev/null 2>&1
ensure_main || echo "!! boot ensure_main failed"
echo "focus: $(focus_line)"
INVER=$(timeout 15 adb -s "$A" shell dumpsys package com.walter.overlay 2>/dev/null | grep -m1 versionName | tr -d ' ')
echo "device: $INVER"
[ "$INVER" = "$VER" ] || { echo "  !! FATAL: version mismatch, aborting"; exit 2; }
sleep 3
# run-as capability first: on a RELEASE install run-as is blocked and every
# adbrw call returns empty — surface that here (not as a confusing "pref OFF").
if ! timeout 8 adb -s "$A" shell "run-as com.walter.overlay id" >/dev/null 2>&1; then
  echo "  !! FATAL: run-as com.walter.overlay is blocked — this is a RELEASE"
  echo "      install (or not debuggable). The golden dump needs the DEBUG"
  echo "      build: pass /tmp/opencode/dbgB.apk (same version, debuggable)."
  exit 4
fi
EN=$(adbrw "cat shared_prefs/deepal.xml" 2>/dev/null | grep -o 'translation_enabled[^\n]*')
echo "prefs: $EN"
grep -q 'value="true"' <<<"$EN" || { echo "  !! translation_enabled OFF — stopping (open the overlay app to reactivate)"; exit 3; }
# Mashina tab
ensure_main
readpills | grep -q "Моя машина" 2>/dev/null || { timeout 12 adb -s "$A" shell input tap 480 2052; sleep 4; }
# LIVENESS PROBE: prove the service is actually reconciling (writes pills.json
# while armed) BEFORE spending 20 min on 11 screens. A release/unbound install
# silently returns nothing and would otherwise burn the whole run (W4-B lesson).
# Placed over a live Mashina screen so the next reconcile has fresh CJK nodes
# to translate -> guaranteed dump.
echo "liveness probe: arm + wait for pills.json write over Mashina..."
adbrw "rm -f files/pills.json files/golden_capture" >/dev/null 2>&1
adbrw "touch files/golden_capture" >/dev/null 2>&1
LIVE=0
HEALED=0
for k in $(seq 1 12); do
  sleep 1.5
  if adbrw "cat files/pills.json" 2>/dev/null | grep -q '"id"'; then LIVE=1; break; fi
  if [ "$HEALED" = "0" ] && [ "$k" -ge 5 ]; then
    # Mid-probe heal: a FRESH REINSTALL leaves the accessibility service
    # UNBOUND (Binding services:{}). Focus changes make AMS re-evaluate the
    # enabled list -> open the overlay (reactivate + process start), then back
    # to Deepal; each focus shift is a rebind trigger.
    HEALED=1
    echo "  probe heal: focus-shift cycle (overlay -> Deepal)"
    timeout 15 adb -s "$A" shell am force-stop com.walter.overlay >/dev/null 2>&1
    sleep 1
    timeout 15 adb -s "$A" shell am start -n com.walter.overlay/.MainActivity >/dev/null 2>&1
    sleep 3
    timeout 25 adb -s "$A" shell am start -n deepal.com.cn.app/.SplashActivity >/dev/null 2>&1
    sleep 3
    continue
  fi
  # nudge a reconcile: tap the same tab (cheap, no navigation)
  timeout 12 adb -s "$A" shell input tap 480 2052 >/dev/null 2>&1
done
adbrw "rm -f files/golden_capture files/pills.json" >/dev/null 2>&1
if [ "$LIVE" != "1" ]; then
  # run-as is BLOCKED on a release install -> adbrw always empty -> this probe
  # fires. Say the cause plainly so it isn't chased as "unbound service".
  if timeout 8 adb -s "$A" shell "run-as com.walter.overlay id" >/dev/null 2>&1; then
    echo "  !! FATAL: service not reconciling (no pills.json while armed)."
    echo "      Reinstall left the accessibility service unbound — re-enable in"
    echo "      Settings > Accessibility, or force-stop com.walter.overlay and reopen."
  else
    echo "  !! FATAL: run-as is blocked — this is a RELEASE install (or not debuggable)."
    echo "      The golden dump needs the DEBUG build: pass /tmp/opencode/dbgB.apk"
    echo "      (same version, debuggable) instead of the release ship APK."
  fi
  exit 4
fi
echo "liveness OK (service is reconciling)"
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
