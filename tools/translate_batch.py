#!/usr/bin/env python3
import json
import time
import urllib.request
import urllib.parse
import sys
import os

INPUT_FILE = os.environ.get("INPUT_FILE", "/tmp/deepal_chinese_strings.json")
DICT_ZH_EN = os.environ.get("DICT_ZH_EN", "/tmp/dict_zh_en.json")
DICT_ZH_RU = os.environ.get("DICT_ZH_RU", "/tmp/dict_zh_ru.json")
SAVE_EVERY = 100
MAX_RETRIES = 3
DELAY = 0.1

def translate(text, target_lang):
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data and data[0] and data[0][0]:
                return "".join(part[0] for part in data[0] if part[0])
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"  Retry {attempt+1} for '{text[:30]}...' in {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  FAILED after {MAX_RETRIES} retries: '{text[:30]}...' - {e}", file=sys.stderr)
    return None

def load_dict(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_dict(path, d):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        strings = json.load(f)

    total = len(strings)
    print(f"Loaded {total} strings")

    dict_en = load_dict(DICT_ZH_EN)
    dict_ru = load_dict(DICT_ZH_RU)
    skipped_en = sum(1 for s in strings if s in dict_en)
    skipped_ru = sum(1 for s in strings if s in dict_ru)
    print(f"Existing: {len(dict_en)} EN, {len(dict_ru)} RU entries")
    print(f"Resuming: will skip already-translated strings")

    last_save = max(len(dict_en), len(dict_ru))
    errors = 0

    for i, s in enumerate(strings):
        en_val = dict_en.get(s)
        ru_val = dict_ru.get(s)

        if en_val is None:
            en_val = translate(s, "en")
            if en_val:
                dict_en[s] = en_val
            else:
                errors += 1
            time.sleep(DELAY)

        if ru_val is None:
            ru_val = translate(s, "ru")
            if ru_val:
                dict_ru[s] = ru_val
            else:
                errors += 1
            time.sleep(DELAY)

        en_display = en_val if en_val else "(skipped)"
        ru_display = ru_val if ru_val else "(skipped)"
        print(f"[{i+1}/{total}] {s[:40]} → en: {en_display[:40]} | ru: {ru_display[:40]}")

        done = max(len(dict_en), len(dict_ru))
        if done - last_save >= SAVE_EVERY:
            save_dict(DICT_ZH_EN, dict_en)
            save_dict(DICT_ZH_RU, dict_ru)
            print(f"  -- Saved progress: {len(dict_en)} EN, {len(dict_ru)} RU")
            last_save = done

    save_dict(DICT_ZH_EN, dict_en)
    save_dict(DICT_ZH_RU, dict_ru)
    print(f"\nDone! EN: {len(dict_en)}, RU: {len(dict_ru)}, Errors: {errors}")

if __name__ == "__main__":
    main()
