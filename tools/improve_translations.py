#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""improve_translations.py — улучшение переводов встроенных словарей
app/src/main/assets/dict_zh_en.json и dict_zh_ru.json через LLM API
(OpenAI-совместимый: Ollama и др.).

Адаптировано из deepal-HU-translate/improve_translations.py (10.10.2026)
под формат нашего приложения:

  - словари плоские: {"zh": "value"} (в HU — список {name, zh, ru});
  - два языка (EN + RU), отдельные прогресс/отчёт на язык;
  - ЗНАЧИМЫЕ отличия конвенций: значения наших словарей рисует
    TextView.setText (plain text, JSON-ассет), а НЕ aapt2-XML ресурсов.
    Поэтому НЕ применяем нормализацию HU ('' -> U+2019, \n -> \\n,
    расэскранирование &amp;) — она сломала бы отображение. Вместо этого
    guard ОТКЛОНЯЕТ &-сущности в выходе, требует теги HTML 1:1 и
    сохранение formatters 1:1.
  - wake-words ***...*** в наших словарях отсутствуют (whitelist пуст);
  - id строки в пайлоаде — её индекс в батче (коротко для модели);
  - strwidth (display_width/hard_cap/is_short_ui) встроен — self-contained.

Режимы:
  --audit      локальный триаж БЕЗ API: дефекты + fit-кандидаты в отчёт
  --defective  (по умолчанию) только проблемные: пустое/CJK/format-мismatch/
               дегенератив/битые теги/слишком короткий длинный
  --fit        укоротить «раздутые» короткие UI-строки (RU/EN заметно
               шире ZH); только короче текущего + hard_cap по символам.
               Прогресс свой: укороченные не трогаем повторно.
  --all        полная перезапись всего словаря (долгий фоновый прогон);
               прогресс resumable.

Аргументы:
  --lang en|ru|both  (по умолчанию both)
  --limit N          максимум строк на запуск (smoke-тест)
  --fresh            сброс progress-файла перед прогон
  --dry-run          показать батчи, не отправляя
  --resume           (alias) — all-прогон и так продолжает с progress

Переменные окружения:
  API_URL (default http://10.0.0.128:11434/v1/chat/completions)
  API_KEY (default ollama), API_MODEL (default Qwen3.8-27B-BF16:latest),
  API_MAX_TOKENS (20000), API_TIMEOUT (900), API_BATCH_SIZE (12),
  API_LONG_THRESHOLD (200 — строки длиннее отправляются по одной),
  API_DEBUG (1 — лог в tools/logs/improve_translations.log),
  DICT_EN, DICT_RU (пути словарей)

Примеры:
  python3 tools/improve_translations.py --audit
  python3 tools/improve_translations.py --defective --lang ru
  python3 tools/improve_translations.py --fit --lang ru --limit 48
  API_DEBUG=1 nohup python3 tools/improve_translations.py --all >> tools/logs/all.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# пути и env
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent          # .../deepal-overlay/tools
REPO_DIR = BASE_DIR.parent
ASSETS = REPO_DIR / "app" / "src" / "main" / "assets"
LOGS = BASE_DIR / "logs"

DICT_PATHS = {
    "en": Path(os.environ.get("DICT_EN", str(ASSETS / "dict_zh_en.json"))),
    "ru": Path(os.environ.get("DICT_RU", str(ASSETS / "dict_zh_ru.json"))),
}
# --all: общий resumable прогресс на язык; --fit: свой (укороченные не
# повторяем; stuck — повторят следующим прогоном, как в HU).
PROGRESS_PATHS = {
    "en": LOGS / "improve_progress_en.json",
    "ru": LOGS / "improve_progress_ru.json",
}
FIT_PROGRESS_PATHS = {
    "en": LOGS / "improve_fit_progress_en.json",
    "ru": LOGS / "improve_fit_progress_ru.json",
}
LOG_PATH = LOGS / "improve_translations.log"

API_URL = os.environ.get("API_URL", "http://10.0.0.128:11434/v1/chat/completions")
API_KEY = os.environ.get("API_KEY", "ollama")
API_MODEL = os.environ.get("API_MODEL", "qwen3.8:27b")
API_MAX_TOKENS = int(os.environ.get("API_MAX_TOKENS", "20000"))
API_TIMEOUT = float(os.environ.get("API_TIMEOUT", "900"))
BATCH_SIZE = int(os.environ.get("API_BATCH_SIZE", "12"))

# Порог длины zh: строки длиннее отправляются ПО ОДНОЙ (в пакете из N такая
# переполняет/обрезает ответ модели и роняет весь батч — конвенция HU).
LONG_THRESHOLD = int(os.environ.get("API_LONG_THRESHOLD", "200"))
# Длинный документ не может уложиться в крошечный перевод.
LONG_RATIO_MIN = 0.25

# Дегенеративные «ответы»-плейсхолдеры, которые модель возвращает, когда
# сдалась. ВАЖНО: "none" ЗДЕСЬ НЕ ЧИСЛИТСЯ — у нас 无 -> "none" (EN) легитимен.
DEGENERATE = {"null", "undefined", "n/a", "nil", "nan"}

DEBUG_ONLY = os.environ.get("API_DEBUG", "").lower() in ("1", "yes", "true")

logger = logging.getLogger("improve")
logger.setLevel(logging.DEBUG)
logger.handlers.clear()
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
if DEBUG_ONLY:
    LOGS.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
_sh = logging.StreamHandler(sys.stderr)
_sh.setLevel(logging.INFO if not DEBUG_ONLY else logging.WARNING)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

# ---------------------------------------------------------------------------
# метрика ширины (стрwidth из deepal-HU-translate, встроен)
# ---------------------------------------------------------------------------

def display_width(s: str | None) -> int:
    """Оценка видимой ширины: CJK/fullwidth = 2 юнита, остальное = 1."""
    w = 0
    for ch in s or "":
        o = ord(ch)
        if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
                or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF):
            w += 2
        else:
            w += 1
    return w


def is_short_ui(zh: str | None) -> bool:
    """Короткая однострочная UI-строка (кнопка/лейбл/элемент списка)."""
    zh = zh or ""
    return zh.count("\n") <= 1 and display_width(zh) <= 14


# Пороги --fit (см. strwidth.py HU; EN строится короче RU — порог строже):
FIT_PARAMS = {"ru": (2.5, 24), "en": (2.0, 20)}  # (soft_ratio, soft_min_ru_w)


def is_over(lang: str, zh: str | None, cur: str | None) -> bool:
    """Триаж fit: перевод заметно шире, чем мог бы быть короткий ZH."""
    zh, cur = zh or "", cur or ""
    if not zh or not cur or not is_short_ui(zh):
        return False
    ratio, min_w = FIT_PARAMS[lang]
    zw, cw = display_width(zh), display_width(cur)
    return zw > 0 and cw > ratio * zw and cw >= min_w


def hard_cap(zh: str | None) -> int:
    """Жёсткий предельный размер (в символах) короткого перевода."""
    zw = display_width(zh or "")
    return max(6, min(28, int(2.0 * zw) + 8))


# ---------------------------------------------------------------------------
# утилиты
# ---------------------------------------------------------------------------

def has_cjk(text: str) -> bool:
    return any(0x4E00 <= ord(c) <= 0x9FFF for c in text or "")


CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
TAG_RE = re.compile(r"<[^<>]*>")
ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#\d+|#x[0-9a-fA-F]+);")
FORMATTER_RE = re.compile(r"%(\d+\$)?(\.?\d*)([dfs])|%%")


def specs(s: str) -> list[str]:
    """Android-форматтеры строки по заданным позициям (порядок важен)."""
    return [m.group(0) for m in FORMATTER_RE.finditer(s or "")]

# ---------------------------------------------------------------------------
# guard (валидация ответа ДО записи; при отклонении значение НЕ меняется)
# ---------------------------------------------------------------------------

def expected_specs(zh: str, cur: str) -> list[str]:
    """Какие форматтеры ОБЯЗАНЫ быть в переводе.

    Если в zh валидный набор %s/%d/… — он. Если в zh '%' есть, но набор
    пустой (битый шаблон в исходнике, напр. "% d" — опечатка Deepal),
    ориентир = форматтеры ТЕКУЩЕГО перевода (существующая конвенция).
    Иначе — никаких."""
    zs = specs(zh)
    if zs or "%" not in zh:
        return zs
    return specs(cur)


def guard(zh: str, new: str, fit: bool = False, cur: str = "") -> tuple[str | None, str | None]:
    """(принятое_значение, причина_отклонения)."""
    new = (new or "").strip()
    if not new:
        return None, "empty"
    if new.lower() in DEGENERATE:
        return None, f"дегенеративный ответ {new!r}"
    need = expected_specs(zh, cur)
    if need != specs(new):
        return None, f"формatters need={need} new={specs(new)}"
    # разметка 1:1 по байтам (теги не трогать, не расшифровывать, не терять)
    if TAG_RE.findall(zh) != TAG_RE.findall(new):
        return None, f"markup изменён: {TAG_RE.findall(zh)} -> {TAG_RE.findall(new)}"
    # &-сущности в выходе невозможны: значение рисуется как plain text —
    # "&amp;" отобразится буквально. (В HU-конвенции их расэскранивали.)
    if ENTITY_RE.search(new):
        return None, f"sущность в выходе: {new[:60]!r}"
    runs = CJK_RUN_RE.findall(new)
    if runs:
        return None, f"CJK осталось: {runs[:4]}"
    # длинный документ не может уложиться в крошечный ответ
    if len(zh) >= LONG_THRESHOLD and len(new) < LONG_RATIO_MIN * len(zh):
        return None, (f"слишком короткий: len={len(new)} < "
                      f"{LONG_RATIO_MIN:g}*len(zh)={len(zh)}")
    # --fit: ОБЯЗАН быть короче текущего по ширине И укладываться в cap
    if fit:
        cur_w, new_w = display_width(cur or ""), display_width(new)
        if cur_w > 0 and new_w >= cur_w:
            return None, f"fit: не короче текущего (w={new_w} >= w_cur={cur_w})"
        cap = hard_cap(zh)
        if len(new) > cap:
            return None, f"fit: не влезает в cap: len={len(new)} > cap={cap}"
    return new, None


def is_defective(zh: str, cur: str) -> bool:
    """Текущее значение дефектное (нужен повторный прогон)."""
    cur = (cur or "").strip()
    if not cur:
        return True
    if has_cjk(cur):
        return True
    if specs(cur) != expected_specs(zh, cur):
        return True
    if cur.lower() in DEGENERATE:
        return True
    if TAG_RE.findall(zh) != TAG_RE.findall(cur):
        return True
    if len(zh) >= LONG_THRESHOLD and len(cur) < LONG_RATIO_MIN * len(zh):
        return True
    return False


# ---------------------------------------------------------------------------
# системный промпт (встроен; адаптирован: авто-GUI Deepal, бренды,
# placeholder-дисциплина, краткость UI-лейблов; без aapt2-конвенций)
# ---------------------------------------------------------------------------

SYS_PROMPT = """Ты — профессиональный переводчик китайского (zh-Hans) на русский или
английский для ПО электромобиля: в-кар-приложение Deepal (HMI, ADAS, OTA,
зарядка, диагностика, сервис).

ЗАДАЧА
Вход — JSON-массив объектов {"id", "zh", "cur"}:
- zh — оригинал (может содержать HTML-теги, плейсхолдеры);
- cur — ТЕКУЩИЙ машинный перевод (часто неверный, может быть пустым).
Верни для каждого id качественный перевод на язык, указанный в задании:
- если cur пустой или фактически неверен — переводи с zh (НЕ копируй cur);
- если cur в целом правильный — верни его без изменений;
- если в cur остались иероглифы или битые плейсхолдеры — почини.

ФОРМАТ ОТВЕТА (строгий)
- ТОЛЬКО валидный JSON-массив; без markdown, без ```json, без текста до/после.
- Каждое id из входа встречается ровно один раз, в том же порядке.

ПЛЕЙСХОЛДЕРЫ (критично)
Сохранять БЕЗ ИЗМЕНЕНИЙ, в том же количестве и порядке, как в zh:
%s, %d, %.1f, %1$s, %2$d, %%, {0}. Не ломать модификаторы:
%1$d остаётся "%1$d" (НЕ "%1$д"). %% (буквальный процент) — как %%.

РАЗМЕТКА / HTML (критично)
Переводи ТОЛЬКО текст между тегами. Теги — побайтово дословно как в zh
(<font color='...'>, <a href=...> и т.п.). Не расшифровывать сущности,
не двойно экранировать, не удалять и не переставлять теги.

БРЕНДЫ И КОДЫ (НЕ переводить, НЕ транслитерировать)
Deepal (深蓝 — это БРЕНД: «темно-синий»/«dark blue» только как цвет ЛАКА
深蓝色, а не как название/марка); Changan (长安); Huawei (华为); ADS;
Amap (高德); WeChat (微信); Alipay (支付宝); QQ Музыка; CarPlay; Carlink;
OTA; ADAS; DTC; CAN; LIN; USB; GPS; HDR; DMS; APA; DVR; Bluetooth;
обозначения моделей (S7, SL03, S05, S07, C650, G318, M07, E700 и т.п.);
коды ошибок, артикулы, URL, email, цифры, единицы измерения.

ГЛОССАРИЙ (единая терминология)
后备箱 — багажник / trunk (НЕ "ствол"!) | 服务 — сервис / Service (контекст
приложения, НЕ "Служить") | 车锁 — замок автомобиля / car lock |
车窗 — окно автомобиля / car window | 空调 — климат-контроль / climate control
| 充电 — зарядка / charging | 电池 — батарея / battery | 刹车 — тормоз / brake
| 倒车影像 — камера заднего вида / rear camera | 倒车雷达 — парктроник /
parking sensors | 车机 — головное устройство / head unit | 设置 — настройки /
settings | 升级 — обновление / update | 校准 — калибровка / calibration
| 故障码 — код неисправности / fault code | 清除故障码 — сброс кодов
неисправностей / clear fault codes | 请勿断电 — не отключайте питание /
do not disconnect power | 请联系经销商 — обратитесь к дилеру / contact your
dealer | 隐私政策 — политика конфиденциальности / privacy policy
| 用户协议 — пользовательское соглашение / terms of service
| 注销 — удаление аккаунта / account deletion | 验证码 — код подтверждения /
verification code | 手机号 — номер телефона / phone number
| 探索 — обзор / Explore | 我的 — мой профиль / Me | 爱车 — моя машина / My Car
| 商城 — магазин / Store

СТИЛЬ
- UI: кратко, без лишней точки в конце, если в zh её нет.
- Короткий zh (2–14 знаков, строка) — лейбл кнопки/вкладки/элемента списка:
  бери кратчайшую ЕСТЕСТВЕННУЮ форму: термин вместо описания, без пояснений
  в скобках, без «функция/режим/система» («Управление/управление чем-либо»
  писать не нужно, если смысл ясен из контекста). Допустимы общепринятые
  сокращения.
- Смысл, плейсхолдеры и пунктуация zh сохраняются ВСЕГДА. Краткость не
  оправдывает потерю смысла.
- Одно понятие — один термин во всём списке.
- Зарегистр и пунктуация — насколько естественно для целевого языка.

САМОПРОВЕРКА ПЕРЕД ОТВЕТОМ
1. JSON валиден; все id на месте, порядок сохранён, дублей нет.
2. Плейсхолдеры zh == плейсхолдеры ответа (количество, порядок, номера).
3. Разметка побайтово как в zh.
4. В ответе нет иероглифов (кроме wake-word в ***...***, если он есть в zh).
5. Никакого markdown/лишнего текста вне JSON.
"""


def build_payload(lang: str, batch: list[dict], hint: str = "") -> dict:
    """batch: [{"zh", "cur"}] по порядку; id — индекс в списке."""
    field = lang
    lang_name = "РУССКИЙ (ру)" if lang == "ru" else "АНГЛИЙСКИЙ (en)"
    rows = [{"id": i, "zh": it["zh"], "cur": it["cur"]} for i, it in enumerate(batch)]
    user = (
        f"Целевой язык: {lang_name}. Для каждого id верни улучшенный перевод "
        f"в поле \"{lang}\".\n"
        f"Вход — JSON-массив объектов. Ответ: ТОЛЬКО JSON-массив вида "
        f'[{{"id": <id>, "{lang}": "<перевод>"}}] — для всех id, порядок как '
        f"во входе, без markdown.\n\n"
        + json.dumps(rows, ensure_ascii=False)
    )
    if hint:
        user += "\n\nВАЖНО, учти при ответе на каждый id: " + hint
    return {
        "model": API_MODEL,
        "max_tokens": API_MAX_TOKENS,
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": user},
        ],
    }


def build_fit_payload(lang: str, batch: list[dict], hard_mode: bool = False,
                      hint: str = "") -> dict:
    """Пайлоад --fit: по id — текущий (переширокий) перевод + opt. cap."""
    rows = []
    for i, it in enumerate(batch):
        row = {"id": i, "zh": it["zh"], "cur": it["cur"]}
        if hard_mode:
            row["max_chars"] = hard_cap(it["zh"])
        rows.append(row)
    field = lang
    if hard_mode:
        user = (
            "Задача — УКОРОТИТЬ существующие переводы (они переполняют "
            "фиксированный UI-лейбл: заметно длиннее китайского оригинала).\n"
            "Для каждого id дано: zh (оригинал), cur (текущий переширокий "
            "перевод), max_chars (жёсткий предел ДЛИНЫ в символах).\n"
            + f'Ответ: ТОЛЬКО JSON-массив [{{"id": ..., "{field}": ...}}] '
            "на все id.\n"
            "ТРЕБОВАНИЯ к каждому:\n"
            "1. длина в СИМВОЛАХ <= max_chars — НЕ ПРЕВЫШАТЬ ни на один символ;\n"
            "2. смысл сохранён, кратчайший естественный UI-термин; без "
            "пояснений в скобках, без «функция/режим/система»;\n"
            "3. плейсхолдеры %s/%d/%.1f/%1$s/%% — 1:1 как в zh (число, "
            "порядок, номера);\n"
            "4. теги HTML (если есть) — побайтово; без CJK; без markdown.\n\n"
            + json.dumps(rows, ensure_ascii=False)
        )
    else:
        user = (
            "Задача — УКОРОТИТЬ существующие переводы (они заметно длиннее "
            "китайского оригинала и переполняют фиксированный UI-лейбл).\n"
            "Для каждого id дано: zh (оригинал), cur (текущий перевод).\n"
            + f'Ответ: ТОЛЬКО JSON-массив [{{"id": ..., "{field}": ...}}] '
            "на все id.\n"
            "ТРЕБОВАНИЯ: каждое новое значение — КОРОЧЕ текущего cur при "
            "сохранённом смысле; кратчайшая естественная UI-форма (термин "
            "вместо описания, без скобок/уточнений); плейсхолдеры 1:1; "
            "теги HTML побайтово; без CJK; без markdown.\n\n"
            + json.dumps(rows, ensure_ascii=False)
        )
    if hint:
        user += "\n\nВАЖНО, учти при ответе на каждый id: " + hint
    return {
        "model": API_MODEL,
        "max_tokens": API_MAX_TOKENS,
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": user},
        ],
    }


# ---------------------------------------------------------------------------
# API (OpenAI-совместимый)
# ---------------------------------------------------------------------------

def _call_api(payload: dict) -> str:
    """POST с ретраями на сетевые/серверные обрывы (Ollama под нагрузкой
    иногда роняет соединение на длинных батчах; модель жива)."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, 4):
        req = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "deepal-overlay/improve",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            wait = 5 * attempt
            logger.warning("API call error (попытка %d/3): %s: %s — sleep %ds",
                           attempt, type(e).__name__, str(e)[:150], wait)
            if attempt < 3:
                time.sleep(wait)
    raise RuntimeError(f"API недоступен после 3 попыток: {API_URL}")


def _extract_content(raw: str) -> str | None:
    """content из OpenAI-конверта (или markdown-обёртка)."""
    cleaned = (raw or "").strip()
    if cleaned.startswith("{"):
        try:
            payload = json.loads(cleaned)
            cleaned = payload["choices"][0]["message"]["content"]
        except (KeyError, json.JSONDecodeError, IndexError, TypeError):
            return None
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        for head in ("json", "py", "python"):
            if cleaned.startswith(head):
                cleaned = cleaned[len(head):].lstrip("\n\r")
                break
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("` \n\r")
    return cleaned


def parse_response(response_text: str) -> list[dict] | None:
    """[{id, ru|en}] из ответа: OpenAI-формат / чистый JSON / fence."""
    cleaned = _extract_content(response_text)
    if cleaned is None:
        return None
    cleaned = cleaned.strip()
    if not cleaned.startswith("["):
        return None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # локальные модели любят нестандартные escape — починить и повторить
        fixed = re.sub(r"\\x([0-9A-Fa-f]{2})", r"\\u00\1", cleaned)
        fixed = fixed.replace(r"\\\"", r"\"")
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, list) else None


# ---------------------------------------------------------------------------
# данные (плоские словари) + прогресс
# ---------------------------------------------------------------------------

def load_dict(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_dict(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)  # атомарно


def load_progress(path: Path) -> set[str]:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")).get("done", []))
        except (OSError, json.JSONDecodeError):
            logger.warning("progress бит — начинаю заново (%s)", path.name)
    return set()


def save_progress(done: set[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"done": sorted(done), "model": API_MODEL,
                   "url": API_URL, "ts": int(time.time())},
                  f, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# точечная починка CJK-остатков (окно вокруг фрагмента; механика из HU)
# ---------------------------------------------------------------------------

REPAIR_MAX_RUNS = 50
REPAIR_CONTEXT = 50


def _parse_repair_response(raw: str) -> list[dict] | None:
    """Lenient-разбор [{n, window}]."""
    cleaned = _extract_content(raw)
    if not cleaned:
        return None
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    out: list[dict] = []
    for mobj in re.finditer(r'\{\s*"n"\s*:\s*(\d+)\s*,\s*"window"\s*:\s*"', cleaned):
        n = int(mobj.group(1))
        pos = mobj.end()
        buf: list[str] = []
        ok = False
        map_esc = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f',
                   'n': '\n', 'r': '\r', 't': '\t'}
        while pos < len(cleaned):
            ch = cleaned[pos]
            if ch == "\\":
                nxt = cleaned[pos + 1] if pos + 1 < len(cleaned) else ""
                if nxt in map_esc:
                    buf.append(map_esc[nxt]); pos += 2; continue
                if nxt == "u" and pos + 5 < len(cleaned) and \
                        re.fullmatch(r"[0-9A-Fa-f]{4}", cleaned[pos + 2:pos + 6]):
                    buf.append(chr(int(cleaned[pos + 2:pos + 6], 16))); pos += 6; continue
                buf.append(nxt or ""); pos += 2; continue
            if ch == '"':
                pos += 1; ok = True
                break
            buf.append(ch); pos += 1
        if not ok:
            return None
        out.append({"n": n, "window": "".join(buf)})
    return out or None


def _repair_cjk(text: str, lang: str) -> str | None:
    """Починить CJK-фрагменты в итоговом переводе без регенерации всего текста:
    для каждого фрагмента — рус. «окно» вокруг него, модель возвращает окно
    целиком исправленным; подстановка в исходный текст."""
    runs = list(CJK_RUN_RE.finditer(text))
    if not runs:
        return text
    if len(runs) > REPAIR_MAX_RUNS:
        return None
    lang_name = "русский" if lang == "ru" else "английский"
    windows = []
    for mm in runs:
        s, e = mm.span()
        ws, we = max(0, s - REPAIR_CONTEXT), min(len(text), e + REPAIR_CONTEXT)
        windows.append(text[ws:we])
    frags = [{"n": i + 1, "window": win} for i, win in enumerate(windows)]
    user = (
        "В готовом переводе (целевой язык: " + lang_name +
        ") остались китайские фрагменты. Для каждого n ниже `window` — "
        "готовый текст, внутри которого ЕСТЬ китайский фрагмент. Верни ЭТО "
        "окно, переведя фрагмент на целевой язык с учётом соседей (смысл, "
        "пробелы/знаки препинания на границах). Всё остальное в окне НЕ "
        "меняй. Ответ: ТОЛЬКО JSON-массив [{\"n\": 1, \"window\": "
        "\"<исправленное окно, целиком>\"}] — один объект на каждый n, без "
        "markdown.\n"
        + json.dumps(frags, ensure_ascii=False)
    )
    parsed = None
    for attempt in range(1, 4):
        try:
            raw = _call_api({
                "model": API_MODEL, "max_tokens": 8000, "temperature": 0.5,
                "messages": [{"role": "system", "content": SYS_PROMPT},
                             {"role": "user", "content": user}],
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("repair API error: %s: %s", type(e).__name__, e)
            raw = None
        if raw is not None:
            parsed = _parse_repair_response(raw)
            if parsed:
                break
            logger.warning("repair: bad JSON (попытка %d); head=%r",
                           attempt, raw[:120])
        time.sleep(1)
    if not parsed:
        return None
    fixed = text
    for i, res in enumerate(parsed):
        if not isinstance(res, dict) or res.get("n") != i + 1:
            return None
        win_fixed = str(res.get("window", "") or "").strip()
        if has_cjk(win_fixed) or win_fixed == windows[i]:
            return None
        fixed = fixed.replace(windows[i], win_fixed, 1)
    if CJK_RUN_RE.search(fixed):
        return None
    return fixed


# ---------------------------------------------------------------------------
# сбор целей и батчи
# ---------------------------------------------------------------------------

def collect_targets(mode: str, lang: str, data: dict) -> list[dict]:
    targets = []
    for zh, cur in data.items():
        zh = (zh or "").strip()
        cur = (cur or "").strip()
        if not zh or not has_cjk(zh):
            continue
        if mode == "defective":
            if not is_defective(zh, cur):
                continue
        elif mode == "fit":
            if not is_over(lang, zh, cur):
                continue
        # "all" — всё
        targets.append({"zh": zh, "cur": cur})
    return targets


def make_chunks(items: list[dict]) -> list[list[dict]]:
    """Длинные (len(zh)>=LONG_THRESHOLD) — ПО ОДНОЙ; короткие — группами."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for it in items:
        if len(it["zh"]) >= LONG_THRESHOLD:
            if cur:
                chunks.append(cur)
                cur = []
            chunks.append([it])
        else:
            if len(cur) >= max(BATCH_SIZE, 1):
                chunks.append(cur)
                cur = []
            cur.append(it)
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------
# отправка батчей (3 попытки → hint по форматтерам → CJK-ремонт → CJK-hint)
# ---------------------------------------------------------------------------

def send_batch(lang: str, chunk: list[dict], fit: bool = False
               ) -> list[tuple[dict, str | None, str]]:
    """Сend один батч. Возврат: [(item, value|None, статус)].

    Статусы: "ok" (принят, отличается от cur), "same" (принят = cur),
    "fail" (модель не вернула строку), иначе — текст guard-reason."""
    by_idx = {i: it for i, it in enumerate(chunk)}
    accepted: dict[int, str] = {}
    guard_rejects: dict[int, str] = {}
    outstanding = list(range(len(chunk)))
    last_responses: dict[int, str] = {}

    def _try(indices: list[int], hint: str = "") -> None:
        nonlocal outstanding
        if not indices:
            return
        items = [by_idx[i] for i in indices]
        payload = (build_fit_payload(lang, items, hint=hint) if fit
                   else build_payload(lang, items, hint=hint))
        try:
            raw = _call_api(payload)
        except Exception as e:  # noqa: BLE001
            logger.warning("API error: %s: %s", type(e).__name__, str(e)[:200])
            time.sleep(2)
            return
        parsed = parse_response(raw)
        if parsed is None:
            logger.warning("bad JSON; head=%r", (raw or "")[:200])
            return
        for res in parsed:
            if not isinstance(res, dict):
                continue
            try:
                idx = int(res.get("id"))
            except (TypeError, ValueError):
                continue
            if idx not in by_idx or idx in accepted:
                continue
            it = by_idx[idx]
            raw_val = res.get(lang) or ""
            if isinstance(raw_val, str) and raw_val.strip():
                last_responses[idx] = raw_val
            value, reason = guard(it["zh"], raw_val, fit=fit, cur=it["cur"])
            if value is not None:
                accepted[idx] = value
                outstanding = [x for x in outstanding if x != idx]
            else:
                guard_rejects.setdefault(idx, reason or "fail")

    # 1) основной проход — до 3 попыток на не вернувшиеся
    for attempt in range(1, 4):
        if not outstanding:
            break
        before = len(outstanding)
        _try(outstanding)
        if len(outstanding) == before:
            logger.info("попытка %d: прогресса нет (%d строк)", attempt, before)
            time.sleep(1)

    # 2) повтор с точным hint'ом на guard-отклонённые по форматтерам
    for idx, why in list(guard_rejects.items()):
        if "формatters" not in why or idx in accepted:
            continue
        it = by_idx[idx]
        need = ", ".join(expected_specs(it["zh"], it["cur"])) \
            or "(без форматтеров, ни одного %)"
        hint = (f'Для id={idx} в переводе ОБЯЗАНЫ быть ровно такие '
                f"форматтеры в таком порядке: {need}. Переведи смысл; эти "
                "форматтеры обязаны СОХРАНИТЬСЯ 1:1 (тоже по порядку). "
                "Проверь до ответа побуквенно.")
        _try([idx], hint=hint)
        if idx in accepted:
            guard_rejects.pop(idx, None)

    # 3) ТОЧЕЧНАЯ починка CJK-остатков (фрагмент + окно, без регенерации)
    for idx, why in list(guard_rejects.items()):
        if "CJK" not in why or idx in accepted:
            continue
        it = by_idx[idx]
        raw_val = last_responses.get(idx, "")
        n_runs = len(CJK_RUN_RE.findall(raw_val))
        if not raw_val or n_runs == 0 or n_runs > REPAIR_MAX_RUNS:
            continue
        repaired = _repair_cjk(raw_val, lang)
        if repaired is None:
            continue
        value, reason = guard(it["zh"], repaired, fit=fit, cur=it["cur"])
        if value is not None:
            accepted[idx] = value
            guard_rejects.pop(idx, None)
            logger.info("CJK-ремонт id=%d: %d фрагм. -> принят (len=%d)",
                        idx, n_runs, len(value))
        else:
            logger.warning("CJK-ремонт id=%d не помог: %s", idx, reason)

    # 4) повтор с hint'ом на CJK, который ремонт не починил
    for idx, why in list(guard_rejects.items()):
        if "CJK" not in why or idx in accepted:
            continue
        hint = (
            f"Для id={idx}: в предыдущем переводе ОСТАЛИСЬ КИТАЙСКИЕ символы. "
            "Переведи каждое такое слово/иероглиф на целевой язык. В ответе "
            "не должно остаться ни одного CJK-символа. Переведи весь текст "
            "целиком, без сокращений и без пропусков."
        )
        _try([idx], hint=hint)
        if idx in accepted:
            guard_rejects.pop(idx, None)

    out: list[tuple[dict, str | None, str]] = []
    for i, it in enumerate(chunk):
        if i in accepted:
            st = "same" if accepted[i] == (it["cur"] or "").strip() else "ok"
            out.append((it, accepted[i], st))
        elif i in guard_rejects:
            out.append((it, None, guard_rejects[i]))
        else:
            out.append((it, None, "fail"))
    return out


def send_fit_batch(lang: str, chunk: list[dict]) -> list[tuple[dict, str | None, str]]:
    """Батч --fit. Два лимита последовательно:
    (1) мягкий — ответ только если КОРОЧЕ текущего (по ширине) и <= cap;
    (2) жёсткий — повтор с явным max_chars в пайлоаде (толькоесли текущий
        длиннее cap — иначе soft покрывает)."""
    by_idx = {i: it for i, it in enumerate(chunk)}
    accepted: dict[int, str] = {}
    reasons: dict[int, str] = {}

    def _run(indices: list[int], hard: bool) -> None:
        items = [by_idx[i] for i in indices if i not in accepted]
        if not items:
            return
        try:
            raw = _call_api(build_fit_payload(lang, items, hard_mode=hard))
        except Exception as e:  # noqa: BLE001
            logger.warning("fit API error: %s: %s", type(e).__name__, str(e)[:200])
            time.sleep(2)
            return
        parsed = parse_response(raw)
        if parsed is None:
            logger.warning("fit bad JSON; head=%r", (raw or "")[:200])
            return
        for res in parsed:
            if not isinstance(res, dict):
                continue
            try:
                idx = int(res.get("id"))
            except (TypeError, ValueError):
                continue
            if idx not in by_idx or idx in accepted:
                continue
            it = by_idx[idx]
            value, reason = guard(it["zh"], res.get(lang) or "",
                                  fit=True, cur=it["cur"])
            if value is not None:
                accepted[idx] = value
            else:
                reasons[idx] = reason or reasons.get(idx, "fail")

    # 1) мягкий проход: до 3 попыток (модель может не вернуть часть id)
    for attempt in range(1, 4):
        todo = list(range(len(chunk)))
        if not todo:
            break
        before = len(todo)
        _run(todo, hard=False)
        still = [i for i in todo if i not in accepted]
        if len(still) == before:
            logger.info("fit мягкий: попытка %d без прогресса (%d)", attempt, before)
            time.sleep(1)

    # 2) жёсткий проход: что мягкий не принял и текущий длиннее cap
    esc = [i for i in range(len(chunk))
           if i not in accepted and len(by_idx[i]["cur"]) > hard_cap(by_idx[i]["zh"])]
    if esc:
        logger.info("fit жёсткий: %d строк с явным cap (max_chars в пайлоаде)", len(esc))
        for i in esc:
            _run([i], hard=True)

    out: list[tuple[dict, str | None, str]] = []
    for i, it in enumerate(chunk):
        if i in accepted:
            out.append((it, accepted[i], "ok"))
        elif i in reasons:
            why = reasons[i]
            st = "not-shorter" if "не короче" in why else (
                "no-fit" if "cap" in why else "fail")
            out.append((it, None, st))
        else:
            out.append((it, None, "fail"))
    return out


# ---------------------------------------------------------------------------
# прогон на один язык
# ---------------------------------------------------------------------------

def run_lang(lang: str, mode: str, limit: int | None, dry_run: bool,
             fresh: bool, report: list) -> int:
    path = DICT_PATHS[lang]
    data = load_dict(path)
    targets = collect_targets(mode, lang, data)

    # прогресс: --all — resumable (фильтр done); --fit — свой файл
    # (укороченные не повторяем); --defective — без фильтра (сам выбирает)
    fit = mode == "fit"
    ppath = FIT_PROGRESS_PATHS[lang] if fit else PROGRESS_PATHS[lang]
    if fresh and ppath.exists():
        ppath.unlink()
    done = load_progress(ppath) if (mode == "all" or fit) else set()
    if mode == "all" or fit:
        pending = [t for t in targets if t["zh"] not in done]
    else:
        pending = list(targets)
    if limit:
        pending = pending[:limit]

    n_long = sum(1 for t in pending if len(t["zh"]) >= LONG_THRESHOLD)
    print(f"[{lang.upper()}] mode={mode} | словарь: {path.name} "
          f"({len(data)} строк) | целей: {len(targets)}, к отправке: {len(pending)}"
          f" (длинных: {n_long}) | batch={BATCH_SIZE} (длинные — по 1) | "
          f"model={API_MODEL}")

    chunks = make_chunks(pending)

    if dry_run:
        print("\n=== DRY RUN: превью первых батчей ===")
        shown = 0
        for chunk in chunks:
            is_long = len(chunk) == 1 and len(chunk[0]["zh"]) >= LONG_THRESHOLD
            print(f"--- batch ({len(chunk)} строк)"
                  + (" [LONG, 1 шт]" if is_long else "") + " ---")
            for it in chunk[:2]:
                print(f"  zh: {it['zh'][:50]!r}")
                print(f"  cur: {it['cur'][:50]!r}"
                      + (f" (w={display_width(it['cur'])}, cap={hard_cap(it['zh'])})"
                         if fit else ""))
            shown += 1
            if shown >= 3:
                break
        if shown == 0:
            print("  (батчей нет)")
        print("\nDry-run: ничего не отправлено.\n")
        return 0

    if not pending:
        print(f"[{lang.upper()}] Отправлять нечего.\n")
        return 0

    updated = same = guarded = failed = 0
    for bi, chunk in enumerate(chunks, 1):
        t0 = time.monotonic()
        results = send_fit_batch(lang, chunk) if fit else send_batch(lang, chunk, fit)
        dt = time.monotonic() - t0
        n_ok = sum(1 for r in results if r[1] is not None)
        logger.info("[%s/%s] batch %d/%d: %.1fs ok=%d rejected=%d",
                    lang, mode, bi, len(chunks), dt, n_ok, len(chunk) - n_ok)
        for it, value, reason in results:
            key = it["zh"]
            if value is not None:
                if value != (it["cur"] or "").strip():
                    data[key] = value
                    updated += 1
                    report.append({"lang": lang, "key": key,
                                   "old": it["cur"], "new": value})
                else:
                    same += 1
                if fit:
                    # в done попадают ТОЛЬКО укороченные: не укорачивать
                    # повторно (риск переусечения смысла)
                    if value != (it["cur"] or "").strip():
                        done.add(key)
                else:
                    done.add(key)
            else:
                if reason == "fail":
                    failed += 1
                else:
                    guarded += 1
                logger.warning("REJECT [%s] %s: %s | zh=%r cur=%r",
                               lang, reason, key[:40], it["zh"][:40], it["cur"][:40])
                if fit:
                    report.append({"lang": lang, "key": key, "old": it["cur"],
                                   "new": None, "status": reason})
        save_dict(path, data)
        save_progress(done, ppath)

    print(f"[{lang.upper()}] ИТОГО: принято {updated}, без изменений {same}, "
          f"guard {guarded}, не переведено {failed}")
    if updated:
        print(f"[{lang.upper()}] словарь обновлён: {path.name}")
    return 0 if failed == 0 else 2


# ---------------------------------------------------------------------------
# --audit: локальный триаж без API
# ---------------------------------------------------------------------------

def audit() -> int:
    out = {}
    for lang in ("en", "ru"):
        data = load_dict(DICT_PATHS[lang])
        defects, fit_cands = [], []
        n_html = n_fmt = 0
        for zh, cur in data.items():
            cur = (cur or "").strip()
            n_html += TAG_RE.search(zh) is not None
            n_fmt += bool(specs(zh))
            reasons = []
            if not cur:
                reasons.append("empty")
            elif has_cjk(cur):
                reasons.append("cjk-left:" + "/".join(CJK_RUN_RE.findall(cur)[:3]))
            if specs(cur) != expected_specs(zh, cur):
                reasons.append(f"fmt zh={specs(zh)} cur={specs(cur)}")
            if cur.lower() in DEGENERATE:
                reasons.append("degenerate")
            if TAG_RE.findall(zh) != TAG_RE.findall(cur):
                reasons.append("markup")
            if len(zh) >= LONG_THRESHOLD and len(cur) < LONG_RATIO_MIN * len(zh):
                reasons.append("too-short-for-long")
            if reasons:
                defects.append({"zh": zh, "cur": cur, "reasons": reasons})
            elif is_over(lang, zh, cur):
                fit_cands.append({"zh": zh, "cur": cur,
                                  "zh_w": display_width(zh),
                                  "cur_w": display_width(cur),
                                  "cap": hard_cap(zh)})
        out[lang] = {"total": len(data), "defs": defects,
                     "fit": fit_cands, "html_entries": n_html,
                     "formatter_entries": n_fmt}
        print(f"\n=== {lang.upper()} ({len(data)} строк; "
              f"HTML-строк: {n_html}, с форматтерами: {n_fmt}) ===")
        print(f"  дефектных: {len(defects)}")
        for d in defects:
            print(f"    [{'; '.join(d['reasons'])}] {d['zh'][:40]!r} -> {d['cur'][:40]!r}")
        print(f"  fit-кандидатов ("
              f"короткий UI, перевод шире порога): {len(fit_cands)}")
        for d in fit_cands[:10]:
            print(f"    zh[{d['zh_w']}]: {d['zh'][:30]!r} -> "
                  f"«{d['cur'][:40]}» (w={d['cur_w']}, cap={d['cap']})")
        if len(fit_cands) > 10:
            print(f"    ... и ещё {len(fit_cands) - 10}")
    LOGS.mkdir(parents=True, exist_ok=True)
    report_p = LOGS / "audit_report.json"
    with open(report_p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nОтчёт: {report_p}")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Улучшение встроенных словарей dict_zh_en/ru.json "
                    "(LLM, OpenAI-совместимый API).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Примеры:")[1] if "Примеры:" in __doc__ else None)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--defective", dest="mode", action="store_const",
                       const="defective", default="defective",
                       help="только проблемные (по умолчанию)")
    group.add_argument("--fit", dest="mode", action="store_const", const="fit",
                       help="укоротить «раздутые» короткие UI-строки")
    group.add_argument("--all", dest="mode", action="store_const", const="all",
                       help="полная перезапись словаря (ресумный прогон)")
    ap.add_argument("--audit", action="store_true",
                    help="локальный триаж без API и написать дефолтный отчёт")
    ap.add_argument("--lang", choices=("en", "ru", "both"), default="both",
                    help="какой словарь (default both)")
    ap.add_argument("--limit", type=int, default=None,
                    help="максимум строк на запуск")
    ap.add_argument("--fresh", action="store_true",
                    help="сброс progress-файла перед прогоном")
    ap.add_argument("--resume", action="store_true",
                    help="alias: all-прогон и так продолжает с progress")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать батчи, не отправляя")
    args = ap.parse_args()

    if args.audit:
        return audit()

    if not args.dry_run and not API_KEY:
        args.dry_run = True
        print("API_KEY пуст — перехожу в dry-run.")

    langs = ("en", "ru") if args.lang == "both" else (args.lang,)
    rc = 0
    report: list = []
    for lang in langs:
        rc |= run_lang(lang, args.mode, args.limit, args.dry_run,
                       args.fresh, report)
    if report:
        LOGS.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        rp = LOGS / f"improve_report_{ts}.json"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"model": API_MODEL, "ts": ts,
                       "changes": report}, f, ensure_ascii=False, indent=1)
        n_changes = sum(1 for r in report if r.get("new"))
        print(f"\nОтчёт: {rp} (изменений: {n_changes})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
