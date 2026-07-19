# Changelog

## v2.9.4 (2026-07-19)
- Словарь обновлён: 5048 записей EN + 5048 RU (извлечено из APK v5398)
- Удалены 383 не-SC записи (HMS Core, японские, традиционные китайские строки)
- versionCode 51

## v2.9.3 (2026-07-19)
- Две кнопки выхода внизу: "Quit (keep accessibility)" и "Quit (disable accessibility)"
- Тестовая кнопка убрана из Actions card
- versionCode 50

## v2.9.2 (2026-07-19)
- `TranslationService.reactivate()` — надёжное восстановление через статический instance (вместо broadcast)
- Тoggle button: скруглённый прямоугольник (GradientDrawable, cornerRadius 12dp)
- versionCode 49

## v2.9.1 (2026-07-19)
- Добавлена тестовая кнопка "Test Quit (keep accessibility)" — выход без отключения accessibility
- `TranslationService.disableTranslation()` — чистит оверлеи, выключает перевод, НЕ вызывает `disableSelf()`
- versionCode 48

## v2.9.0 (2026-07-19)
- **Quit**: полностью отключает accessibility service (`disableSelf()`)
- **Quit**: плавающая кнопка и все оверлеи пропадают мгновенно
- **Quit**: при следующем запуске требуется повторное включение accessibility
- **Без тумблера**: поведение quit всегда одинаковое (выход = отключение сервиса)
- Исправлена рекурсия `recreate()` в `onResume()` — заменён на `refreshStatus()`
- Исправлены утечки `HttpURLConnection` (disconnect в finally)
- Исправлены утечки InputStream в `loadDictFromAssets()` (try-with-resources)
- `dictLoaded` и `translating` — `volatile` (видимость между потоками)
- `collectChineseNodes()`: `Pattern.compile` вместо `replaceAll` на каждый вызов
- `scanWindow()`: SharedPreferences читаются 1 раз за вызов
- `translateBatch()`: один `mainHandler.post()` вместо N (батч)
- Удалён пустой метод `setToggleVisible()`
- Удалён `BroadcastReceiver.ACTION_QUIT` (заменён на прямой вызов `quit()`)
- `TranslationService.quit()` — статический метод, синхронный вызов
- versionCode 47

## v2.8.0 (2026-07-18)
- **Quit**: приложение сворачивается, плавающая кнопка пропадает
- **Quit**: при следующем запуске приложения снова требуется permission на accessibility
- Quit: убран `disableSelf()` — сервис не перезапускается системой
- Quit: убраны `Settings.Secure`, `killProcess`, `stopService`
- Quit: при повторном открытии приложения автоперевод активируется через `ACTION_SHOW`
- `scan_all` по умолчанию выключен
- OverlayView: `ScheduledExecutorService` → `View.postDelayed`
- `translateBatch()`: raw `Thread` → `ExecutorService`
- `collectChineseNodes()`: добавлен `child.recycle()`
- `updateNotification()`: throttle 2s
- Все silent catch блоки заменены на `Log.w()`
- explicit imports вместо `android.widget.*`
- dependencies: appcompat 1.7.0, material 1.12.0, constraintlayout 2.2.0
- `minifyEnabled true` для release сборки

## v2.7.8 (2026-07-18)
- Quit: `disableSelf()` + автоматическая очистка оверлеев через broadcast
- Добавлена кнопка «Завершение…» при выходе (задержка 3с перед закрытием)
- Убрана зависимость от `WRITE_SECURE_SETTINGS`
- Исправлен toggle button при первой установке (retry каждые 2с до получения overlay permission)
- Версия отображается в интерфейсе

## v2.7.1 (2026-07-18)
- Настройки применяются сразу при переключении (без кнопки Apply)
- Удалена кнопка «Apply Settings»

## v2.7.0 (2026-07-18)
- Переключатель темы (Light / Dark / System) в настройках
- `AppCompatDelegate.setDefaultNightMode()` применяется до `super.onCreate()`
- Локализация: EN (Light/Dark/System) + RU (Светлая/Тёмная/Системная)

## v2.6.6 (2026-07-18)
- i18n: все строки интерфейса вынесены в `values/strings.xml` (EN) + `values-ru/strings.xml` (RU)
- UI Language toggle: переключение языка интерфейса с `recreate()`
- Dark overlay option: тёмный фон `#DD1A1A1A` + белый текст
- Word wrap option: перенос строк (по умолчанию выключен)
- Все кнопки действий унифицированы в `materialButtonOutlinedStyle`

## v2.6.5 (2026-07-18)
- Fixed `getDefaultDisplay().getMetrics()` → `getResources().getDisplayMetrics()` (Android 17 fix)

## v2.4.2
- Замена dropdown на `MaterialButtonToggleGroup` для выбора языка

## v2.4.1
- Тёмная тема (следует за системной)
- Исправлены русские строки
- Умный перенос текста (макс 13 символов/строка, разрыв по пробелам)

## v2.4.0
- **Material Design 3** полный редизайн
- MD3 темы (светлая + тёмная)
- Edge-to-edge дизайн
- Карточки для секций настроек

## v2.3.3
- Исправлен запуск Deepal (fallback на SplashActivity)
- Quit: безопасный выход без отключения accessibility

## v2.3.2
- Круглая кнопка ON/OFF (зелёная/серая)
- Quit: отключение accessibility через `Settings.Secure`

## v2.3.1
- Кнопка «Open Deepal»
- Плавающая кнопка toggle (ON/OFF)

## v2.3.0
- Кнопка Quit

## v2.2.2
- Удаление HTML-тегов из текста
- Фильтр: требует ≥30% китайских символов для перевода

## v2.2.1
- Исправлен парсинг JSON (корректная декодировка `\u003c` и других escape-последовательностей)

## v2.2.0
- Многострочный текстовый wrap для длинных переводов

## v2.1.1
- Исправлено определение фона: проверка только 3 ближайших parent-элементов

## v2.1.0
- Автоматическое определение фона каждого overlay (Toolbar, AppBar и т.д.)

## v2.0.3
- Очистка кэша при смене языка перевода

## v2.0.2
- Overlay совпадает с фоном приложения (непрозрачный)

## v2.0.1
- Overlay поверх оригинального текста (нативный вид)

## v2.0.0
- **Embedded dictionary**: 4889 строк китайский→английский + 4889 китайский→русский
- Мгновенный перевод без API-запросов
- Google Translate API как fallback для строк не из словаря

## v1.6.4
- Устранён flicker, debounce уменьшен до 350мс

## v1.6.3
- Исправлен flicker, размер шрифта, overlay при выходе из приложения

## v1.6.2
- Очистка overlay при смене приложения

## v1.6.1
- Шире overlay для длинных переводов

## v1.6.0
- Event-driven accessibility service (оптимизация производительности)

## v1.5.2
- Устранён flicker: overlay привязаны к позиции, обновление in-place

## v1.5.1
- Исправлены stale overlay при скролле

## v1.5.0
- Исправлен flicker и смещение

## v1.4.0
- **Inline translation overlay**: замена оригинального текста переводом

## v1.3.0
- Улучшенная диагностика, всегда видимый overlay, уведомления

## v1.2.0
- Debug overlay + улучшения accessibility

## v1.1.1
- Исправлена проверка overlay permission для Android 17

## v1.1.0
- Первый релиз
- Overlay fix, debug mode, отображение версии
