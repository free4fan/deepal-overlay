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
2. При обнаружении китайского текста — ищет перевод в embedded словаре (4889 строк)
3. Если строка не найдена в словаре — отправляет запрос к Google Translate API
4. Перевод отображается как overlay поверх оригинального текста

## Технические детали

- **Package**: `com.walter.overlay`
- **Min SDK**: 26 (Android 8.0)
- **Target SDK**: 34 (Android 14)
- **Embedded dictionaries**: `dict_zh_en.json` (4889 строк), `dict_zh_ru.json` (4889 строк)
- **Overlay**: `TYPE_APPLICATION_OVERLAY` с автоматическим подбором фона
- **Flicker-free**: обновление overlay in-place без пересоздания

## Сборка

```bash
./gradlew assembleDebug
cp app/build/outputs/apk/debug/app-debug.apk deepal-overlay.apk
```

Требуется JDK 17.

## Обновление словаря перевода

При выходе новой версии приложения Deepal словарь китайских строк нужно обновить.

### 1. Извлечение строк из APK

Установите последнюю версию Deepal, затем через ADB выгрузите ресурсы:

```bash
# Дамп всех строковых ресурсов
adb shell dumpsys accessibility > /tmp/deepal-resources-dump.txt

# Или через aapt
aapt2 dump resources path/to/deepal.apk > /tmp/deepal-values-dump.txt
```

### 2. Подготовка списка китайских строк

Из дампа извлеките уникальные китайские строки. Формат:
```json
["строка1", "строка2", ...]
```

Подготовленный файл: `/tmp/deepal-chinese-strings.json`. В проекте также есть `/tmp/deepal-string-mapping.json` — маппинг original_key → Chinese text.

### 3. Запуск перевода

```bash
python3 tools/translate_batch.py
```

Скрипт:
- Читает все строки из `INPUT_FILE` (`/tmp/deepal_chinese_strings.json`)
- Для каждой строки переводит через Google Translate API (EN + RU)
- Сохраняет прогресс каждые 100 строк
- Пропускает уже переведённые строки (при дозапуске)
- Результат: `dict_zh_en.json` и `dict_zh_ru.json`

Параметры (в начале скрипта):
- `DELAY = 0.1` — задержка между запросами
- `SAVE_EVERY = 100` — как часто сохранять прогресс
- `MAX_RETRIES = 3` — повторы при ошибке сети

### 4. Копирование в проект

```bash
cp /tmp/dict_zh_en.json app/src/main/assets/
cp /tmp/dict_zh_ru.json app/src/main/assets/
```

## Лицензия

Личный проект. Не для распространения.
