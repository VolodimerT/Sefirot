# Strict referee YC SHADOW — Issue #60, четвёртое семейство

База verified FOULS #66 `1675092228ffaa13e270b9439c13144b82b3519b`,
12/12 CI. Existing source/observation-v2/QC/shared family matrix/CLI reused;
CORE, source schema, old receipts/seals и решения не меняются.

## Обязательный gate

Exact fixture/kickoff + confirmed prematch referee ID/receipt; YC/game и
YC/foul; finite risk 0–1; Stake YC settlement/rules; отсутствие cleaner market;
независимая calibration reference и verified positive EV. Нет любого условия
или contradicted/late/malformed — HOLD/PASS/D/stake=0. Bool/NaN/risk вне
диапазона, negative rates, неположительный EV, wrong rule/hash и cleaner
market не могут дать допуск. Existing referee QC проверяет identity/season/
UTC/raw hash и сохраняет REFEREE_ORIGIN_NOT_ATTESTED.

Данные caller и local checksum не независимое подтверждение. Даже все
правильно сформированные prerequisites не снимают SOURCE_ORIGIN blocker:
independent attestation authority/runtime пока не установлен/не проверен.
source_verified=true/extra fields отвергаются. Public gate никогда не
выдаёт неподтверждённую вероятность/EV/permission, они null/false.

Own YC count baseline lab хранит mean по unique fixture IDs одного referee,
не получает foul/goal rates и не превращает фолы в ЖК. Неизвестные counts не
нулевые; разные referee scope отвергаются. Это uncalibrated typed synthetic
math lab, не real fit. Без source/referee/calibration/price proofs numeric P
даже из этого mean не публикуется.

## Воспроизведение

```sh
python scripts/small_family_shadow.py --family YC --as-of 2026-10-13T22:50:00+00:00
python -m unittest discover -s tests -p test_referee_yc_issue60.py -v
python scripts/verify_release.py
```

YC FT/1H/2H MATCH/HOME/AWAY: 9 matrix rows, origin/history/model/calibration/
rules/P-EV blockers. model_parameters/P/EV=null, referee gate HOLD, stake=0.
Builder UNPRICED: actual combined quote и verified joint отсутствуют, marginal
P не умножаются. RED/SECOND_YELLOW/BOOKING_POINTS не выдаются за YC.
Реальных новых provider receipts, dataset, calibrated model или bets нет.

6 new tests: every missing prerequisite, complete caller/fake attestation,
bool/nonfinite/risk/rates/EV, late referee/cleaner market/rules/hash, own YC
counts vs foul surrogate/referee identity, no-source/source-QC matrix.
Full release и exact OS/Python + actual PostgreSQL mirror/budget обязательны;
точные counts/head/tree/links в draft PR после проверки.
All src/core MODEL_MODULES/Policy and old reports/source/seals/approvals preserved.
No main/prod/deploy/keys/paid provider requests/refit/money/LIVE.

После зелёного CI завершается инженерная очередь #57–61. Empirical model
quality и source-driven real SHADOW остаются блокированы отсутствием verified
whole-league season/receipts/calibration/HOLDOUT/rules/referee; #61 остаётся
прототипом без actual remote endpoint/device verification.

Local release: 1376 tests, 1372 pass + 4 PostgreSQL skips; integrity/replay=true.
