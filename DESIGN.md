# DESIGN — позиционирование оверлеев (id-first)

Статус: **инфраструктура + аудит** (бриф `prompt.md`, шаги 1–2).
Поведение приложения этим коммитом **не изменено**.

## Сетka безопасности (с v2.10.44 и далее)

- **Golden**: `tools/capture_golden.sh` снимает `tools/golden/<run>/<screen>/`
  (a11y.xml + overlays.txt + **pills.json** + screenshot.png + manifest.txt);
  список экранов — `tools/screens.json`. Скрипт сам запускает Deepal (только
  через `.SplashActivity`), включает сессию золотых дампов (flag) и снимает
  её по выходу (`trap disarm EXIT`). Перед правкой: снять baseline; после:
  `python3 tools/diff_golden.py <baseline> <new> --json report.json`.
- **Источник rects пилюль = приложение** (`pills.json`). Overlay-окна
  (а11y-сервис) **невидимы** и `uiautomator dump` (0 узлов), и `dumpsys window`
  (окна без package/title) — проверено live на устройстве. Пока существует
  флаг `files/golden_capture` (создаётся и удаляется скриптом `run-as`, то
  есть только на DEBUG-установке; на релизе `run-as` заблокирован → механизм
  автоматически инертен, 0 затрат на прод-пути) app сам пишет в
  `files/pills.json` точную геометрию активных пилюль: `key, id, text,
  node[x0,y0,x1,y1], pill[x,y,w,h], est, sp, fsPx` (троттлинг 700 мс).
- **HARD-сигналы = дельта baseline→new** (правила 3/5 брифа: «было/стало»,
  любой ненулевой сдвиг не по цели = регрессия, подлежащая обоснованию):
  `NODE-CHG` — а11y-узел сдвинулся/поменял размер на >±2px;
  `PILL-CHG` — пилюля сдвинулась **относительно своего узла** на >±2px,
  появилась или исчезла. «Относительно узла» — скролл приложения двигает
  узел и пилюлю вместе → это не дефект (проверено синтетическим тестом).
  view_profiles в HARD-пути **не участвует** → baseline чистой сборки
  всегда зелёный.
- **ADVISORY (информационно, не гейт)** — абсолютная id-first модель
  покрытия: позиция CJK-бега из профиля (`g=center` → центр узла,
  `p=padStart` → контент-край, иначе — оба кандидата), label/block,
  overhang ≤2px за рамку узла. Это **вход для шага 3** (пометка mixed
  gravity), а не истина: пока профиль неполный, advisory печатает
  противоречия профиль↔код как находки аудита, а не как фейлы. Обнаружено:
  `tvTopTitle` (профиль `g=center, p=20dp`; код ставит CJK на контент-край
  ~56px) → mixed-кейс для шага 3.
- **moratorium** (жесткий, до отмены):
  1. новых геометрических гейтов `if (h>X && y<Y && w>est·k)` — НЕ ДОБАВЛЯТЬ;
     сначала доказать невозможность через id-профиль;
  2. один PR = одна причина (≥2 гейтов — разбить);
  3. правка только с golden-diff: baseline до, diff после, в отчёте — список
     изменённых узлов и причина каждого;
  4. регрессия (нецелевой сдвиг) — либо баг, либо «осознанно расширено» в
     CHANGELOG;
  5. словарь (dict) и геометрия — в разных релизах.
- **Мораторий не распространяется** на: fix-правки внутри существующего гейта
  (корректность условия), расширение `view_profiles.json` (шаг 3) и
  подключение профилей вместо гейтов (шаг 4) — это и есть вывод из петли.

## Инвентаризация гейтов (аудит v2.10.43)

Источники: `InlineOverlayManager.computeLayout` + `view_profiles.json`
(7265 id: 1940 со sp, `fw` 3248, `sl` 6626, `g` 762, `p` 317).
id без профиля (`tvNegative`, `tvPositive`, `tv_title`, `tv_content`, `tv1`,
`tvAirTile`, `tvAir`, …) — те, что реально живут на серверных/диалоговых
экранах и НЕ декомпилировались из layout'ов.

| Гейт | Условие (px) | Обслуживает (id) | В профиле? | Замена id-first'ом | Вердикт |
|---|---|---|---|---|---|
| start-lock `sl` | id in startLockedIds (6626) | left-anchor для всех start-закреплённых id | есть | — (УЖЕ id-first) | держать |
| (A) `toolbarCentered` | !sl && !standalone && y<320 && 40<x<0.6·sw && w>4.5·est && h<74 | toolbar-заголовки (`action_title_tv` и род. — 635 id с g=center) | ЧАСТИЧНО (g есть) | `g=center` + не fw | **удалить после шага 3** (профиль покрывает) |
| (B) `buttonCentered` | !sl && x≤60 && w≥0.83·sw && 96≤h<120 && w>2.5·est | full-width кнопки (`exit_button`: fw+sl) | есть (fw) | `fw=1` + `g=center` | **удалить после шага 3** |
| (C1) `isPageHeaderId` | id == tvTopTitle | page-header | есть: tvTopTitle = [24sp, g:center, p:20] | профиль (p=20dp — сверить с 24dp-веткой, расхождение px) | **уже id-first; сверить p** |
| (C2) header-geometry | standalone && x≤30 && w≥0.95·sw && y<340 | headers без id | нет (по определению) | — | **держать как fallback** (замерзший) |
| (D) `emptyCentered` | standalone && x≤30 && w≥0.95·sw && y>340 && !tvTopTitle | empty-state (当日无旅程数据 960×106) | id-узла НЕТ | id-профиль g=center | **удалить после шага 3** (добавить id в профиль) |
| (E) `centeredLabel` | !standalone && !wide && w≤1.35·est+2 && W≥est && screenMid±24 && clears≥0.7 | AC «Включить» 92w c480, «Привязать» 180w c480, dialog title; НЕ сетки (732 c794) | id-узлов НЕТ (tvAir/tvBind/tv_title) | id-профиль g=center | **держать как fallback** до шага 3; затем удалить |
| (F) `dialogButton` | ddx==0 && W>est && !sl && x>30 && 0.28sw<w<0.65sw && 96≤h≤130 && w>2·est → hug: W=H=node, stadium, fs=est(≤shrink), g=CENTER | кнопочная пара диалогов (tvNegative/tvPositive — НЕТ в профиле) | НЕТ | профиль: новый флаг `btn` (hug-кнопка) + `g=center` | **держать как fallback**; шаг 3 добавит флаг, шаг 4 — переезд |
| shape-классы (width/H) | `standaloneRow` w>2.5est && h>1.8est; `wideRow` w>2.5est (без closeRow); `tallIconBox` w≤1.35est+2 && 1.6<h/est<6; `looseRow` w>1.7est && h>1.8est; `completeBlock` shown≈implied строк; `singleLineNode` h≤1.9est | контейнерные узлы, icon-плитки, абзацы | N/A (геометрия заполнения) | — (это не позиционирование, а измерение «кто что за узел») | **замерзшие — не растят** |

### Что реально можно удалить на следующем шаге (после шага 3)

1. **(A)** — 635 id уже с `g=center`; заголовок toolbar из них. Доказательство:
   `action_title_tv`, `action_bar_title`, `action_right_tv` в профиле.
2. **(B)** — `exit_button` = [None, {fw:1, sl:1}] full-width кнопка.
3. **(D)** — добавить id empty-state (узнать на golden-захвате: `a11y.xml`
   отдалит id для当日无旅程数据) + `g=center`.
Порядок: шаг 3 (расширить профиль: `g` безусловно + `p` + `btn` + mixed-
пометка) → снять baseline goldens v2.10.43 → удалить (A)/(B)/(D) + включить
`layoutFromProfile` (шаг 4) → `diff_golden` обязан показать только цели.

### Известное расхождение (профиль vs код)

- (C1) использует инсэт `24dp` («content edge ~55-59px») при том, что
  `tvTopTitle.p = 20dp`. 20·2.25=45 ≠ 55-59 — проверить на golden-после
  переключения на `p`. Пока: НЕ переключать (это сдвиг геометрии = отдельный
  релиз с diff'ом).
