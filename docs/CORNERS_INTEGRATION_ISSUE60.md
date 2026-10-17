# Corners SHADOW integration — Issue #60, первое семейство

База — verified #59 `b1961710bcb0634e40e013260a4c38d963bad1a4`, #63,
12/12 CI. Переиспользуется существующий draft PR #25 и его независимая count
модель, CSV provenance/temporal diagnostics и tests от exact
`eb4f8f1c1ee24cd55499b794c60d429e12a4e089`. Финальный integration commit имеет
оба parent SHA: история #25 сохраняется; старый CORE stack не переносится.
Base PR меняется на текущую evidence ветку; main не сливается.

## Модель и исправления

CORNERS_SHADOW_V0 считает отдельные corner counts, venue means/shrinkage,
Poisson/NB и rate stress. Goal lambda не используется, CORE модель не импортирует
эти три research modules. Наличие математической реализации не означает
проверенных параметров, source coverage, calibration или денежного допуска.

Подтверждённый дефект: walk_forward для 1H DOUBLE_CHANCE брал исход из FT counts.
Контрольный synthetic пример: old realized rate=1, correct half rate=0;
это не результат настоящего HOLDOUT. Теперь observations и P имеют один
период, как и existing frozen split evaluator.
FT/1H/2H TOTAL/TEAM/DOUBLE_CHANCE поддержаны; 2H — разность FT/1H одного
typed CornerMatch, с отдельной dispersion счётчиков. Это не перенос goal
distribution, не предположение о 50% и не заполнение отсутствующего raw 2H.
Raw/QC неизвестный период остаётся missing; публичная матрица ничего не
вычисляет из отсутствующих counts.

PUSH integer / half-line contracts проверяются legacy и новыми tests;
VOID/withdrawn/live/AET/PEN исключает existing observation-v2 QC, не превращает
их в LOSS или нули. Требования 90 минут и actual available_at сохраняются.

## Один QC и публичная матрица

```sh
python scripts/small_family_shadow.py --family CORNERS --as-of 2026-10-13T21:45:00+00:00
python scripts/small_family_shadow.py --family CORNERS --as-of 2030-02-03T12:00:00+00:00 --input normalized-observation-batch.json --output /absolute/new-shadow.json
python -m unittest discover -s tests -p test_corners_integration_issue60.py -v
python scripts/verify_release.py
```

Переиспользованы #37/#38 audit_dataset / source bindings; новый importer не
создаётся. Input — existing normalized batch. Original raw receipt hashes/
UTC/revision/IDs/license/season/league/definition/period обязаны проверяться
existing adapter/QC. Local checksum не source attestation.
Без входа denominator/coverage/model_parameters/P/EV=null. Даже полностью
структурный supplied batch имеет origin/calibration/rules blockers.
На каждом FT/1H/2H MATCH/HOME/AWAY matrix row:
source → history coverage → independent count model → calibration →
quote rules → P/EV status. fit_allowed=false, stake=0, execution=false.

Legacy fit/price/split функции остаются внутренним mathematical lab,
RESEARCH_UNVALIDATED, без money. Публичная команда их не запускает и не выдаёт
raw conditional projection за проверенную вероятность реального матча.
Реальные файлы для training не предоставлены; новый real fit не выполнялся.
CSV source_accepted — старое caller assertion, не сертификат; он не переносится
в verified source, coverage или публичные P/EV.

Builder: UNPRICED/RESEARCH_ONLY, joint_probability=null, combined price=null,
marginal_product_used=false. Нужны actual combined bookmaker quote и
independently verified joint distribution на том же fixture/period/rules.

## Проверки и границы

Исходные 21 legacy corner tests переиспользованы. 7 новых regressions:
wrong half-DC result, 2H same-row counts/PUSH, no-source null matrix,
whole manifest/zeros без origin admission, missing counts, caller fake
attestation и отказ неизвестному семейству. Старый negative 2H contract
перенесён на EXTRA_TIME: 2H теперь предусмотренная новая функция;
negative quarter/GOALS/DC-line сохраняются.

Полный release и exact Ubuntu/Windows × 3.11/3.13, PG mirror/budget обязательны.
Итоговые counts, SHA/tree/CI и non-model code_hash — в описании #25 после проверки.
MODEL_MODULES/Policy, #59 source corrections и старые source/seal/reports
сохранены; added src research modules меняют exact code_hash явно.
No main/production/deploy/provider calls/secrets/real fit/monetary promotion.

Следующий небольшой draft increment: SHOTS/SOT; затем FOULS, затем strict
referee YC. Реальная лицензированная whole-league season/receipts/calibration/
holdout/Stake rules остаются блокерами каждого семейства.

Локально: 1359 tests, 1355 pass + 4 PostgreSQL skips; replay/integrity=true.
code_hash `1e950f252eb1fed9cfd67644433df31379a7d33582085e871bb194cd5600b7db`; model_hash `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`; policy_hash `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`.
