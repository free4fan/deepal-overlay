# DESIGN — позиционирование оверлеев (id-first)

Статус: **инфраструктура + аудит** (бриф `prompt.md`, шаги 1–2).
Поведение приложения этим коммитом **не изменено**.

## Сетka безопасности (с v2.10.44 и далее)

- **Goldens**: `tools/capture_golden.sh` снимает `tools/golden/<run>/<screen>/`
  (a11y.xml + overlays.txt + screenshot.png + manifest.txt); список экранов —
  `tools/screens.json`. Перед правкой: снять baseline в `tools/golden/<baseline>`.
  После: `python3 tools/diff_golden.py <baseline> <new> --json report.json`.
- **Инварианты покрытия** (`diff_golden.py`, вместо «хардгардов 211×64 @ y1120»):
  - `label` (короткий CJK в широком узле — кнопки, плитки): пилюля покрывает
    CJK-бег в **обеих** его позициях (у левого края узла И по центру — пока
    позиция не описана флагом `g` в профиле) и не вылезает за рамку узла
    больше `OVERHANG_MAX=2` px с каждой стороны;
  - `block` (CJK заполняет/переносится в узле — абзацы): пилюля не вылезает
    за ВЕРХ/ЛЕВО узла; рост вниз в чистый зазор — разрешён и логируется,
    не фейлит.
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
