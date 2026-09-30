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

### 2. Запуск перевода

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

### 3. Копирование в проект

```bash
cp /tmp/dict_zh_en.json app/src/main/assets/
cp /tmp/dict_zh_ru.json app/src/main/assets/
```

## Лицензия

This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or distribute this software, either in source code form or as a compiled binary, for any purpose, commercial or non-commercial, and by any means.

See [LICENSE](LICENSE) for full text.
