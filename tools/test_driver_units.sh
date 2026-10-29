#!/usr/bin/env bash
# =============================================================================
# tools/test_driver_units.sh — OFFLINE unit tests for capture_retest.sh
# =============================================================================
# No device. Tests the EXACT functions shipped in capture_retest.sh by
# extracting them verbatim and running them against REAL W4-C capture
# fixtures (tools/golden/W4_C_clean_96/*). Regression gate for the two
# silent bugs that degraded W4-A/W4-B/W4-C identically (found 10-20: the
# user watched the live W4-C run and reported the wrong scroll direction):
#   BUG1 (stdin):   `readpills | python3 - args <<'PY' ... PY` — an explicit
#                   heredoc redirect OVERRIDES the pipe, so python read its
#                   own source on stdin; cy_of()/pill_c() always returned
#                   empty -> every anchor/to_top/sentinel read cy=? and the
#                   off-screen fallback scrolled the wrong way.
#   BUG2 (a11y rx): validator regex captured the resource-id VALUE
#                   INCLUDING the closing quote ('title"' != 'title') ->
#                   overlap mathematically ALWAYS 0 -> every valid deepal
#                   tree was dropped as "stale" (a11y=0 on all 11 screens
#                   of every run, verified offline on W4-C artifacts).
# Plus: anchor() off-screen fallback must REVEAL BELOW (finger up, drag +)
# because all 11 canonical screens start at the TOP.
# =============================================================================
set -uo pipefail
D="$(cd "$(dirname "$0")/.." && pwd)"
S="$D/tools/capture_retest.sh"
FIX="$D/tools/golden/W4_C_clean_96"        # real (degraded-run) fixtures
# Committed W4_C subset = mashina_top/pills.json + shop/pills.json +
# manifest.txt (screenshots/overlays.txt stay untracked, run dirs are
# gitignored). The shop KEEP assertion below additionally needs the session
# a11y dump /tmp/opencode/w4c_g.xml (not in the repo) — skipped when absent.
WORK=$(mktemp -d /tmp/opencode/unit_test.XXXX)
trap 'rm -rf "$WORK"' EXIT
FAIL=0
ok()  { echo "  ok:   $*"; }
die() { echo "  FAIL: $*"; FAIL=1; }

# Use the real W4_C fixture when present (strongest, real capture). Fall back
# to a small SYNTHETIC but shape-identical fixture so the gate runs on a bare
# clone (no device, no capture) — the assertions below are fixture-relative
# (they recompute expected cy/center from the same fixture), so a consistent
# synthetic fixture exercises the same code path. This is what keeps the gate
# green everywhere, not only on a machine that ran W4-C.
FIXTURE="$FIX/mashina_top/pills.json"
if [ ! -f "$FIXTURE" ]; then
  FIXTURE="$WORK/fixture_pills.json"
  cat > "$FIXTURE" <<'EOF'
[
  {"id":"tv_main_name","text":"Моя машина","node":[10,68,600,140],"pill":[24,72,560,132]},
  {"id":"tv_main_car_update","text":"Припаркован | Обновлено","node":[24,214,820,44],"pill":[24,214,820,44]},
  {"id":"tv1","text":"Замок","node":[40,1040,200,64],"pill":[40,1040,200,64]}
]
EOF
  echo "  (using synthetic fixture — real W4_C golden not on this machine)"
fi

# Device-side reader stubbed with real fixture data (the functions call
# readpills as a subroutine; overridable by definition).
readpills() { cat "$FIXTURE"; }

extract_fn() { # $1=function-name -> its full definition to stdout
  awk -v fn="$1" '$0 ~ fn"\\(\\) \\{"{f=1; print; next} f{print; if($0=="}") exit}' "$S"
}
eval "$(extract_fn cy_of)"
eval "$(extract_fn pill_c)"

echo "== BUG1: cy_of / pill_c consume piped stdin (previously: always empty) =="
got="$(cy_of tv_main_name Моя)"
case "$got" in
  ''|*[!0-9]*) die "cy_of returned '$got' (want integer cy)";;
  *) ok "cy_of(tv_main_name@Моя) => cy=$got";;
esac
want="$(python3 -c '
import json,sys
for e in json.load(open(sys.argv[1])):
    if e.get("id")=="tv_main_name" and e.get("text","").startswith("Моя"):
        n=e["node"]; print(int((n[1]+n[3])/2)); break
' "$FIXTURE")"
[ "$got" = "$want" ] && ok "cy equals fixture node midpoint ($want)" || die "cy=$got != fixture midpoint $want"

gotc="$(pill_c tv_main_name "Моя машина")"
wantc="$(python3 -c '
import json,sys
for e in json.load(open(sys.argv[1])):
    if e.get("id")=="tv_main_name" and e.get("text","")=="Моя машина":
        x,y,w,h=e["pill"]; print(int(x+w/2), int(y+h/2)); break
' "$FIXTURE")"
[ "$gotc" = "$wantc" ] && ok "pill_c matches fixture center ($wantc)" || die "pill_c '$gotc' != fixture '$wantc'"

empty="$(cy_of no_such_id_123 "")"
[ -z "$empty" ] && ok "unknown id -> empty, no crash" || die "unknown id -> '$empty'"

echo "== anchor(): off-screen fallback reveals BELOW (finger up, drag +) =="
# BEHAVIORAL test (source-grep would false-positive on the bug-history
# comment): stub drag/focus_ok, call anchor() with an id that is NOT in the
# fixture (=> every read is empty => the off-screen branch runs), and record
# the actual drag() calls. All of them must be POSITIVE dy (reveal below).
drag()   { echo "DRAG $1"; }
focus_ok() { return 0; }
eval "$(extract_fn anchor)"
CALLS="$(anchor no_such_id_xyz "" 200 2>/dev/null | grep '^DRAG' || true)"
[ -n "$CALLS" ] || die "anchor() never called drag() (empty-read loop broken?)"
echo "$CALLS" | grep -q '^DRAG -' \
  && die "anchor() dragged DOWN (reveal above) on empty reads: $(echo "$CALLS" | head -1) — the user-observed W4-C failure direction" \
  || ok "anchor() empty-read drags are all UP (reveal below): $(echo "$CALLS" | head -1) ..."
echo "$CALLS" | grep -q '^DRAG 500' && ok "empty-read magnitude = 500px chunk" || die "empty-read chunk is not 500"

echo "== BUG2: a11y validator (unquoted id capture; keep/reject both ways) =="
VALID="$(awk -v m='a11y.xml" "$R/$s/pills.json"' 'index($0,m){f=1;next} f&&/^PY$/{exit} f{print}' "$S")"
[ -n "$VALID" ] || die "could not extract the shipped validator heredoc"
run_validator() { python3 -c "$VALID" "$1" "$2"; }

# KEEP-1: a tree containing exactly the fixture's own ids (100% overlap).
python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
nodes="".join("<node resource-id=\"deepal.com.cn.app:id/%s\"/>" % e.get("id","") for e in d if e.get("id"))
open(sys.argv[2],"w").write("<hierarchy>%s</hierarchy>" % nodes)
' "$FIXTURE" "$WORK/self_tree.xml"
run_validator "$WORK/self_tree.xml" "$FIXTURE" \
  && ok "KEEP: full-overlap deepal tree accepted (rc=0)" \
  || die "KEEP: full-overlap deepal tree REJECTED (BUG2 or threshold broken)"

# KEEP-2: the real mid-run shop tree (pulled from the device 10-20) vs the
# real shop pills — both W4-C artifacts; the shop ids (title/tvNotShowTip*)
# are literally present in that dump.
if [ -f /tmp/opencode/w4c_g.xml ] && [ -f "$FIX/shop/pills.json" ]; then
  if run_validator /tmp/opencode/w4c_g.xml "$FIX/shop/pills.json"; then
    ok "KEEP: real shop tree vs real shop pills accepted (BUG2 fixed live-evidence)"
  else
    die "KEEP: real shop tree vs real shop pills REJECTED — validator still broken"
  fi
else
  echo "  SKIP: real w4c_g.xml / shop fixture not present (KEEP-1 covers the logic)"
fi

# REJECT: a synthetic foreign (systemui shade) tree must be dropped.
cat > "$WORK/shade_tree.xml" <<'EOF'
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0"><node index="0" text="" resource-id="android:id/status_bar_icon_container" class="android.widget.FrameLayout" package="com.android.systemui" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][960,2142]" drawing-order="0" /></hierarchy>
EOF
run_validator "$WORK/shade_tree.xml" "$FIXTURE" \
  && die "REJECT: foreign/shade tree was KEPT (validator lets garbage through)" \
  || ok "REJECT: foreign/shade tree dropped (rc=1)"

echo
if [ "$FAIL" = "0" ]; then echo "ALL DRIVER-UNIT TESTS PASSED"; else echo "DRIVER-UNIT TESTS FAILED"; fi
exit "$FAIL"
