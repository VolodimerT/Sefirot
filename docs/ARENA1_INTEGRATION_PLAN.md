# ARENA 1.0: P0–P1, 11.10.2026

Один изолированный PR поверх **#14**, exact base
`ee433953e643cf60a793e6392131b77dc5ea5617`. Новая диагностика повторно
использует `arena_control`, `arena_shadow.ROLE_SPECS` и canonical CORE math.
Ни один прежний script или `src/sefirot` файл не заменён. P2–P4 не выполняются.

## Проверенная база

Полные HEAD/base/tree, changed files и все CI jobs:
[ARENA1_INVENTORY_20261011.json](../reports/ARENA1_INVENTORY_20261011.json).
Это свежая инвентаризация GitHub, не утверждение об интеграции всех PR.

| PR | HEAD (prefix) | Base PR / branch | CI на этом HEAD |
|---|---|---|---|
| #12 | 59c02bc5 | #11 / stability | 4 PASS |
| #13 | 19a81f96 | #12 | 2 PASS, Windows 3.11 FAIL, 3.13 cancelled |
| #14 | ee433953 | #13 | 4 PASS |
| #21 | 121a5801 | #19 | 4 PASS |
| #23 | 67e10930 | #21 | 4 PASS |
| #24 | 3707cbf2 | #23 | 4 PASS |
| #22 | 9b88d130 | #21 | 4 PASS |
| #25 | eb4f8f1c | #11 | 4 PASS |
| main | 96dd9586 | CORE 2.3 | 4 PASS; это не V3 |

Минимальный общий ancestor #14/#24 — `053ad5a07c4732c5062ac6a445fc1d61b1c2a119`.
Семь MODEL_MODULES на heads #12–14/#21–25 побайтно совпадают. Но exact
`code_hash` #14/#24 отличается: CLI, data-session, football transport/query
и offline_panel. Совпадение model hash не разрешает воспроизводить seal
другой сборкой. В #14 исправлен обнаруженный в #13 Windows POST transport
сбой; его failing job — 113234885631, 612 тестов, два WinError 10053.

ARENA scripts отсутствуют в дереве #24; V3 `research/prediction_edge_v3/arena.py`
является отдельной ablation над заданными векторами/vetoes. Он не вызывает
production ARENA, не связывает оригинальные ledger decisions и не меняется.
В этом PR нет cherry-pick CORE/collector из #24, Chat Bridge или CORNERS.
Будущая интеграция требует отдельного PR и CI: нельзя копировать одноимённые
CORE/AGENTS/report файлы между цепочками. Новый namespace — `research/arena1`.
Диагностика этого этапа работает с original BASELINE seals #14; DC/SOS
артефакты и их код остаются на #21 неизменными. Их seal adapter — будущая задача.

## Трасса и границы

`sports packet → engine.prepare → Service.capture → predictions + RECORD`
фиксирует original probability, pool, sports.as_of, sealed_at и build.
`Service.decide → decisions + RECORD` сохраняет original PASS/BET, точные
quotes и cutoff. Новый код никогда не вызывает decide для backfill.
`arena_control.sports_view/ledger_bridge → arena1.bind → hunt → Finding`
создаёт пять price-blind sports views и три priced views после seal.
`registry.register` записывает отдельный create-once JSON; `read_bound`
повторяет вычисления с исходными входами, а не доверяет одному SHA.
Поздний result остаётся в прежних `arena_control_forward`/`forward_scorecard`;
нового эмпирического scorecard, cohort или denominator здесь не создаётся.

Сохраняются fixture_id = sports.match.id, prediction_id = original seal ID,
decision_id = exact original decision или null, model_hash = model_code_hash,
code_hash и policy_hash = Policy fingerprint, canonical market/line и
REGULATION_90. `sports.as_of ≤ seal ≤ review cutoff < kickoff`.
FACT: `observed ≤ published ≤ received ≤ sports.as_of`; available_at в view
равен received_at, помечен LOCAL_RECEIPT_ONLY; независимого attestation нет.
Quotes: original post-seal receipt, exact contract, observed ≤ received ≤
review cutoff; CLOSE/другой период/новая линия отвергаются. Future/target
result в sports input отвергается. SQLite дополнительно проверяется RO:
quick_check, FK, payload/SQL identity columns. Модель, Policy, production
ledger и archived seals не переписываются.

## Реализованный P1

- Frozen typed `Finding`: identity, role/phase, premise, exact market,
  evidence/groups/time, mechanism, unknowns, falsifier, version и запрет денег.
- Error Hunter: raw score projection mismatch, impossible PUSH mass,
  unverified exact calibration bin, stale/missing quote, result leakage,
  source replication, history concentration, duplicate/unsupported legacy veto,
  shared-score Builder dependence и отсутствие combined price.
- Devil's Advocate: только воспроизводимые типизированные hypotheses;
  свободный факт/изменённый механизм/чужой ID отвергается. UNKNOWN не PASS.
- Counterfactual Lab: фиксированные ±10% λ с clipping [0.01,12], удаление
  крупнейшего historical score, target-team и league groups. Все векторы
  проходят simplex. Это SENSITIVITY_ONLY, не событие/интервал/поправка.
  Season и lineup-effect без модели явно UNKNOWN.
- HARD_BLOCK новой диагностики сохраняет local-ledger-bound директиву,
  требует конкретного original FACT support
  и воспроизводимого sealed avoid_result → exact result contract механизма.
  Unbound directive остаётся UNKNOWN. Не относится к TOTAL/BTTS;
  reviewer не создаёт глобальный veto. System
  integrity/build/time failure прекращает обработку; unbound source — stop.
- Прежние v0.2 authored vetoes читаются как UNVERIFIED, не автоматически
  применяются 1.0. Несколько ролей с одним доказательством не голосуют.
- Builder probe — одна фиксированная пара HOME/BTTS из original pool,
  проекция общей raw score mass, не новый экспресс/модель. EV всегда null:
  verified combined odds и независимой joint calibration здесь нет.

Два воспроизводимых старых контрпримера: v0.2 принимает TOTAL veto по
`fact-home_team` без entailment; Repository.verify не обнаруживает подмену
SQL match_id при неизменном payload. Новая диагностика проверяет оба.

## Использование

    python scripts/arena_diagnostic.py --prediction original.json --quotes quotes.json --at ORIGINAL_REVIEW_ISO --db original.sqlite --registry private/arena1
    python scripts/arena_diagnostic.py --prediction original.json --quotes quotes.json --at ORIGINAL_REVIEW_ISO --db original.sqlite --verify private/arena1/RECORD_HASH.json

Не передавать invented/backdated timestamps; запуск на историческом cutoff —
offline reconstruction, не новая prospective регистрация. Без quotes/decision
возвращается UNKNOWN; без БД источник unbound и global stop. --legacy-reviews
читает старые восемь findings groups; --findings допускает только полный
воспроизводимый 1.0 replay. Нет API/LLM mode, новых основных CLI commands.
Create-once — гарантия приложения, не защита от администратора файлов.

## Приёмка и стоп

Негативные тесты используют actual CORE.capture/SQLite на явно synthetic
fixtures. Полный release проверяет также все старые тесты, demo/replay,
synthetic backtest и уже просмотренный retrospective audit. Последние
два не являются новыми испытаниями модели. Локальная сводка — в новом
ARENA1_P0_P1_RELEASE.json; финальные HEAD/CI — в PR и отчёте поставки.

REAL_TRAIN=0, NEW_INDEPENDENT_HOLDOUT=0, ARENA_INCREMENTAL_BENEFIT=NOT_MEASURED.
LLM calls=0, cost/latency=null, KEEP_SHADOW, INSUFFICIENT_REAL_DATA.
Исторически плохая калибровка, полезность/вред veto, phi, CLV и доходность
не доказаны. Для них требуются подлинная независимая выборка и receipts;
v0.2 forward VOID handling также требует отдельной проверки в P2.
После этого P0–P1 PR остановиться. Следующее единственное действие —
review/приёмка P1; P2 начинать только по отдельному поручению.
