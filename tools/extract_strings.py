#!/usr/bin/env python3
"""Extract unique Chinese strings from a Deepal APK and diff against current dicts.

Usage:
    python3 tools/extract_strings.py /path/to/deepal.apk

Outputs:
    /tmp/deepal_chinese_strings.json  - all unique CJK values (for translate_batch.py)
    /tmp/deepal_missing_strings.json  - values not yet in the embedded dicts
    prints version info + diff summary
"""
import json
import os
import re
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT_EN = os.path.join(PROJECT, "app/src/main/assets/dict_zh_en.json")
DICT_RU = os.path.join(PROJECT, "app/src/main/assets/dict_zh_ru.json")
OUT_ALL = "/tmp/deepal_chinese_strings.json"
OUT_MISSING = "/tmp/deepal_missing_strings.json"

CJK = re.compile(r"[\u4e00-\u9fff]")


def badging(apk_path):
    try:
        out = subprocess.run(
            ["aapt2", "dump", "badging", apk_path],
            capture_output=True, text=True, timeout=120,
        ).stdout
        m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", out)
        if m:
            return f"{m.group(1)} v{m.group(3)} (versionCode {m.group(2)})"
    except Exception:
        pass
    return "unknown"


def extract_resources(apk_path):
    out = subprocess.run(
        ["aapt2", "dump", "resources", apk_path],
        capture_output=True, text=True, timeout=600,
    )
    if out.returncode != 0:
        sys.exit(f"aapt2 dump resources failed: {out.stderr.strip()[:500]}")
    return out.stdout


def cjk_strings(dump):
    lines = dump.split("\n")
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"\s+type string id=\d+ entryCount=(\d+)", line)
        if m and int(m.group(1)) > 100:
            start = i
            break
    if start is None:
        sys.exit("string resource type not found in aapt2 dump")

    values = set()
    current = False
    for line in lines[start + 1:]:
        if re.match(r"\s+type \d+ id=", line):
            break
        if re.match(r"\s+resource 0x[0-9a-f]+ string/\S+", line):
            current = True
            continue
        # config lines: () default, (zh-rCN), (v30), (en-rUS)...
        m = re.match(r'\s+\(([^)]*)\) "(.*)"\s*$', line)
        if not m or not current:
            continue
        conf, value = m.group(1), m.group(2)
        # prefer Chinese configs; default config is Chinese in Deepal
        if conf in ("", "zh-rCN", "zh-rTW") and CJK.search(value):
            values.add(value.strip())
    return values


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    apk_path = sys.argv[1]
    if not os.path.exists(apk_path):
        sys.exit(f"not found: {apk_path}")

    print(f"APK: {apk_path}")
    print(f"App: {badging(apk_path)}")

    dump = extract_resources(apk_path)
    strings = cjk_strings(dump)
    print(f"Unique CJK strings in APK: {len(strings)}")

    with open(DICT_EN, encoding="utf-8") as f:
        dict_en = json.load(f)
    with open(DICT_RU, encoding="utf-8") as f:
        dict_ru = json.load(f)

    missing = sorted(s for s in strings if s not in dict_en or s not in dict_ru)
    removed = sorted(k for k in dict_en if k not in strings)
    print(f"Dict entries: {len(dict_en)} EN / {len(dict_ru)} RU")
    print(f"NEW (in APK, not in dict): {len(missing)}")
    print(f"GONE (in dict, not in APK): {len(removed)}")

    for s in missing:
        print(f"  + {s}")

    with open(OUT_ALL, "w", encoding="utf-8") as f:
        json.dump(sorted(strings), f, ensure_ascii=False, indent=1)
    with open(OUT_MISSING, "w", encoding="utf-8") as f:
        json.dump(missing, f, ensure_ascii=False, indent=1)
    print(f"\nWrote {OUT_ALL}")
    print(f"Wrote {OUT_MISSING}")
    if missing:
        print("\nNext step: INPUT_FILE=... python3 tools/translate_batch.py")


if __name__ == "__main__":
    main()
