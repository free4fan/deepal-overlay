# Deepal Translate Overlay

Приложение для Android, которое переводит китайский интерфейс приложения **Deepal (深蓝汽车)** на английский или русский язык в реальном времени.

Работает через Accessibility Service — читает текст из любого приложения и показывает перевод поверх оригинального текста.

## Установка

1. Скачайте `deepal-overlay.apk`
2. Установите: `adb install deepal-overlay.apk`
3. Откройте приложение и выдайте два разрешения:
   - **Accessibility Service** — для чтения текста из приложений
   - **Overlay** — для отображения переводов поверх других приложений
4. Нажмите **Open Deepal** для запуска приложения

## Использование

- **Плавающая кнопка ON/OFF** (правый верхний угол) — включение/выключение перевода
- **Quit** — отключает accessibility service, закрывает приложение (при следующем запуске нужно снова включить accessibility в настройках)
- **Open Deepal** — запускает приложение Deepal

### Настройки (в MainActivity)

- **UI Language** — язык интерфейса (English / Русский)
- **Translation Language** — язык перевода (English / Русский)
- **Scan all apps** — переводить во всех приложениях (не только в Deepal)
- **Word wrap** — перенос длинных переводов на несколько строк
- **Dark overlay** — тёмный фон для всех переводов
- **App theme** — тема приложения (Светлая / Тёмная / Системная)

## Требования

- Android 8.0+ (API 26)
- Приложение Deepal установлено на устройстве

## Как работает

1. Accessibility Service отслеживает события окон (открытие, скролл, смена контента)
2. При обнаружении китайского текста — ищет перевод в embedded словаре (4856 строк)
3. Если строка не найдена в словаре — отправляет запрос к Google Translate API
4. Перевод отображается как overlay поверх оригинального текста:
   полупрозрачный тёмный scrim в контенте, непрозрачный тёмный в зоне тулбара,
   коротким подписям в узких узлах (кнопки, заголовки) передаётся центрирование

## Технические детали

- **Package**: `com.walter.overlay`
- **Min SDK**: 26 (Android 8.0)
- **Target SDK**: 34 (Android 14)
- **Embedded dictionaries**: `dict_zh_en.json` (4856 строк), `dict_zh_ru.json` (4856 строк)
- **Overlay**: `TYPE_APPLICATION_OVERLAY` с адаптивным фоном (scrim/тёмный по зоне)
- **Flicker-free**: обновление overlay in-place без пересоздания
- **Точный размер**: ширина меряется `Paint.measureText`, кегль в px (не SP)
- **Word wrap**: нативный перенос по фактической ширине (max 8 строк)
- **Кэш**: LRU (20000), постоянного файла `translation_cache.json`

## Сборка

```bash
./gradlew assembleDebug
cp app/build/outputs/apk/debug/app-debug.apk deepal-overlay.apk
```

Требуется JDK 17.

## Обновление словаря перевода

При выходе новой версии приложения Deepal словарь китайских строк нужно обновить.

### 1. Извлечение строк из APK

```bash
python3 tools/extract_strings.py /path/to/deepal.apk
```

Скрипт:
- печатает версию приложения (package/versionName/versionCode)
- извлекает уникальные китайские строки из `resources.arsc` (дефолтный конфиг + zh-rCN + zh-rTW)
- считает дифф со словарём: новые строки (в APK, нет в словаре) и исчезнувшие
- пишет `/tmp/deepal_chinese_strings.json` (все строки) и `/tmp/deepal_missing_strings.json` (только новые)

### 2. Перевод новых строк (машинный)

```bash
python3 tools/translate_batch.py
```

Скрипт:
- Читает строки из `INPUT_FILE` (по умолчанию `/tmp/deepal_chinese_strings.json`)
- Для каждой строки переводит через Google Translate API (EN + RU)
- Сохраняет прогресс каждые 100 строк
- Пропускает уже переведённые строки (при дозапуске)
- Результат: `dict_zh_en.json` и `dict_zh_ru.json`

Пути переопределяются env-переменными `INPUT_FILE`, `DICT_ZH_EN`, `DICT_ZH_RU`.
Переводить только новые строки:

```bash
INPUT_FILE=/tmp/deepal_missing_strings.json DICT_ZH_EN=/tmp/dict_zh_en.json DICT_ZH_RU=/tmp/dict_zh_ru.json \
  python3 tools/translate_batch.py
```

Параметры (в начале скрипта):
- `DELAY = 0.1` — задержка между запросами
- `SAVE_EVERY = 100` — как часто сохранять прогресс
- `MAX_RETRIES = 3` — повторы при ошибке сети

### 3. Улучшение качества (LLM)

Машинный перевод (Google) даёт ошибки: битые форматтеры (`%1$стикер`),
оставшийся CJK, неточные термины (`后备箱`→«ствол»), «раздутые» UI-лейблы.
Их правит `tools/improve_translations.py` (LLM через OpenAI-совместимый API,
адаптирован из проекта `deepal-HU-translate`):

```bash
python3 tools/improve_translations.py --audit          # триаж без API: дефекты + fit-кандидаты
python3 tools/improve_translations.py --defective      # починить только проблемные (по умолчанию)
python3 tools/improve_translations.py --fit --lang ru  # укоротить раздутые короткие UI-строки
python3 tools/improve_translations.py --all            # полная перезапись (глубокий фоновый прогон)
```

Режимы:
- `--audit` — локальный отчёт (`tools/logs/audit_report.json`) без сети;
- `--defective` — пустые/CJK в переводе/битые форматтеры/битые HTML-теги/
  дегенеративные значения/слишком короткие длинные;
- `--fit` — короткие UI-лейблы, где перевод заметно шире китайского
  (страница переполняется): два лимита — «короче текущего» и жёсткий cap
  в символах; укороченные не трогаются повторно (свой progress);
- `--all` — весь словарь, resumable (прогресс — `tools/logs/improve_progress_*.json`).

Общее: `--lang en|ru|both`, `--limit N`, `--fresh` (сброс progress),
`--dry-run`, `API_DEBUG=1` (лог — `tools/logs/improve_translations.log`).
Изменения пишутся в `tools/logs/improve_report_<ts>.json` — сверять до пуша.

Env: `API_URL` (default `http://10.0.0.128:11434/v1/chat/completions`),
`API_KEY`, `API_MODEL` (default `Qwen3.8-27B-BF16:latest`), `API_BATCH_SIZE`.

Особенности под наше приложение (vs HU-проект): значения словаря рисует
`TextView.setText` (plain text, JSON-ассет), поэтому скрипт НЕ применяет
aapt2-конвенции (замена `'` на U+2019, `\n`→`\\n`, расэскранирование
`&amp;`), а guard отклоняет ответы с `&`-сущностями и требует сохранение
HTML-тегов и форматтеров (`%s`, `%1$d`, …) 1:1. Бренды в промпте:
`深蓝` = **Deepal** (не «темно-синий»), `高德` = Amap и т.д.

### 4. Копирование в проект

```bash
cp /tmp/dict_zh_en.json app/src/main/assets/
cp /tmp/dict_zh_ru.json app/src/main/assets/
```

## Лицензия

This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or distribute this software, either in source code form or as a compiled binary, for any purpose, commercial or non-commercial, and by any means.

See [LICENSE](LICENSE) for full text.
