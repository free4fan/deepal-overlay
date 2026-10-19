#!/usr/bin/env python3
"""Device-free self-test for tools/diff_golden.py (golden harness health).

Runs the synthetic fixture matrix that must hold for every release:
  A. identical runs            -> 0 hard  (baseline of a clean build is green)
  B. node+pill scroll together -> NODE-CHG only, no PILL-CHG (scroll is not a
                                   layout regression)
  C. node fixed, pill drifted  -> PILL-CHG (real layout defect)
  D. pill widened in place     -> PILL-CHG (size/coverage changed: R edge
                                   moved away from the node's right edge)

No device, no adb. Usage: python3 tools/test_diff_golden.py
Exit 0 = all scenarios behave as expected.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIFF = HERE / "diff_golden.py"
TMP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/opencode/gt_selftest")


def pill(key, pid, txt, node, p, est, sp=24.0):
    return {"key": key, "id": pid, "text": txt, "node": node, "pill": p,
            "est": est, "sp": sp, "fsPx": sp * 2.25}


def a11y(nodes):
    body = "".join(
        '<node text="%s" resource-id="app:id/%s" class="android.widget.TextView" '
        'package="app" bounds="%s"/>\n' % (t, i, b)
        for (i, t, b) in nodes)
    return "<hierarchy>\n%s</hierarchy>" % body


def screen(root, name, nodes, pills):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "a11y.xml").write_text(a11y(nodes), encoding="utf-8")
    (d / "overlays.txt").write_text("", encoding="utf-8")
    (d / "pills.json").write_text(json.dumps(pills), encoding="utf-8")
    (d / "manifest.txt").write_text("screen=%s\n" % name, encoding="utf-8")


def run_diff(base, new):
    p = subprocess.run([sys.executable, str(DIFF), str(base), str(new)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def hard_count(out):
    for line in out.splitlines():
        if line.startswith("HARD signals"):
            return int(line.rsplit(":", 1)[1].strip())
    return None


def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    base, new = TMP / "base", TMP / "new"

    A_NODES = [("tvTitle", "停车", "[100,300][330,360]")]
    # A: identical
    A_P = [pill("100,300", "tvTitle", "Остановка", [100, 300, 330, 360],
                [98, 300, 234, 60], 230)]
    screen(base, "A", A_NODES, A_P)
    screen(new, "A", A_NODES, A_P)

    B_NODES_B = [("tvTitle", "停车", "[100,300][330,360]")]
    B_NODES_N = [("tvTitle", "停车", "[110,300][340,360]")]
    B_PB = [pill("100,300", "tvTitle", "Остановка", [100, 300, 330, 360],
                 [98, 300, 234, 60], 230)]
    B_PN = [pill("110,300", "tvTitle", "Остановка", [110, 300, 340, 360],
                 [108, 300, 234, 60], 230)]  # moved WITH the node
    screen(base, "B", B_NODES_B, B_PB)
    screen(new, "B", B_NODES_N, B_PN)

    C_NODES = [("tvTitle", "停车", "[100,300][330,360]")]
    C_PB = [pill("100,300", "tvTitle", "Остановка", [100, 300, 330, 360],
                 [98, 300, 234, 60], 230)]
    C_PN = [pill("100,300", "tvTitle", "Остановка", [100, 300, 330, 360],
                 [83, 300, 234, 60], 230)]  # pill alone, -15
    screen(base, "C", C_NODES, C_PB)
    screen(new, "C", C_NODES, C_PN)

    D_NODES = [("tv1", "窗", "[720,1129][907,1175]")]
    D_PB = [pill("720,1129", "tv1", "Окна", [720, 1129, 907, 1175],
                 [720, 1120, 211, 64], 61)]
    D_PN = [pill("720,1129", "tv1", "Окна", [720, 1129, 907, 1175],
                 [720, 1120, 251, 64], 61)]  # widened +40 in place
    screen(base, "D", D_NODES, D_PB)
    screen(new, "D", D_NODES, D_PN)

    (base / "manifest.txt").write_text(
        "screen=A\nscreen=B\nscreen=C\nscreen=D\n", encoding="utf-8")
    (new / "manifest.txt").write_text(
        "screen=A\nscreen=B\nscreen=C\nscreen=D\n", encoding="utf-8")

    # run 1: base vs base -> clean, 0 hard
    rc1, out1 = run_diff(base, base)
    # run 2: base vs new -> B(NODE-CHG)+C(PILL-CHG)+D(PILL-CHG) = 3 hard
    rc2, out2 = run_diff(base, new)

    fails = []
    if rc1 != 0 or "RESULT: clean" not in out1 or hard_count(out1) != 0:
        fails.append("A: identical runs must be clean, 0 hard "
                     "(rc=%s, hard=%s)" % (rc1, hard_count(out1)))
    if rc2 == 0 or hard_count(out2) != 3:
        fails.append("B/C/D: expected exactly 3 hard signals, "
                     "got rc=%s hard=%s" % (rc2, hard_count(out2)))
    for name, marker in (("B", "NODE-CHG MOVED tvTitle"),
                         ("C", "PILL-CHG tvTitle|Остановка"),
                         ("D", "PILL-CHG tv1|Окна")):
        if marker not in out2:
            fails.append("%s: expected line missing: %r" % (name, marker))
    # A must contribute no hard lines
    for line in out2.splitlines():
        if "[A]" in line and ("NODE-CHG" in line or "PILL-CHG" in line):
            fails.append("A leaked a hard line: %r" % line.strip())

    print("self-test fixture: %s" % TMP)
    print("run1 (base vs base): rc=%s hard=%s %s"
          % (rc1, hard_count(out1), "PASS(clean)" if rc1 == 0 else "FAIL"))
    print("run2 (base vs new) : rc=%s hard=%s (want 3: B+ C+ D+)"
          % (rc2, hard_count(out2)))
    if fails:
        print("FAIL:")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("OK: all 4 scenarios behave as expected")


if __name__ == "__main__":
    main()
