# Deepal Translate — Overlay-сервис перевода китайских приложений

Отдельное Android-приложение (без модификации оригинального APK).
Перехватывает текст из Chinese UI через Accessibility Service,
переводит через Google Translate RPC и рисует overlay поверх строк.

## Структура
```
deepal-overlay/
├── app/
│   ├── build.gradle              # Dependencies: material, appcompat
│   └── src/main/
│       ├── AndroidManifest.xml   # Service + permissions declaration
│       ├── res/xml/accessibility_config.xml  # Service config
│       └── java/com/walter/overlay/
│           ├── TranslationService.java    # Main logic
│           └── MainActivity.java          # Settings UI
```

## Сборка
1. Установить Android SDK + Gradle (или Android Studio)
2. `cd deepal-overlay && ./gradlew assembleDebug`
3. APK: `app/build/outputs/apk/debug/app-debug.apk`

## Установка на телефон
```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

После установки: включить сервис в Настройки → Специальные возможности.

## Как работает
1. Приложение запускает **AccessibilityService** с правом просмотра содержимого окна
2. При смене экрана (`TYPE_WINDOW_STATE_CHANGED`) сканирует все `TextView` окна
3. Для строк с китайскими символами (CJK Unicode range 4E00-9FFF) делает запрос к Google Translate RPC
4. Рисует полупрозрачный yellow overlay TextView поверх оригинала
5. При уходе из приложения — overlays удаляются

## Настройка
- `TARGET_LANG` в TranslationService.java: `"en"` или `"ru"`  
- `MONITORED_PACKAGES` — список пакетов для мониторинга (пусто = все приложения)
- Для Russian: изменить TARGET_LANG на "ru"

## Ограничения
- Google Translate RPC — бесплатный, без ключа, но есть rate limiting (~50 req/min)
- Android 10+ требует явного разрешения на overlay от пользователя
- Overlay позиционируется в (0,0) относительно экрана — может не точно совпадать с оригиналом
