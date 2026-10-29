# SHOTS/SOT SHADOW — Issue #60, второе семейство

База verified corners #25 exact `94a932af3de08714b02ee3ca690c423ae6c7a12d`;
6/6 required CI jobs. Один маленький family increment, existing #37/#38 QC
и shared family matrix/CLI переиспользованы, новый importer не создаётся.

Own paired same-fixture shot/SOT counts: baseline shot mean + conditional
binomial thinning SOT|shots. Support всегда 0<=SOT<=shots; методы не получают
goal lambda/corner forecast rates. Используется existing count PMF как общая
математика распределения, с собственной shot mean. Это internal uncalibrated
math lab, не новый real fit/validated probability или часть CORE.
Pair input exact fields/unique fixtures, integer known counts; null/bool не нули.
Все-zero shots — known mean=0, thinning ratio=null (не выдумывается 0/0).

Public SHOTS/SOT FT/1H/2H MATCH/HOME/AWAY matrix: source→history→model→
calibration→rules→P/EV; 18 rows. Missing archive/verified origin/definition/
coverage/calibration/rules => parameters/P/EV=null, fit_allowed=false, stake=0.
Source definitions, periods и team identities проверяет existing observation QC.
SOT>shots quarantined; paired counts не создают независимые fixtures.
Builder joint cross-metric P/actual combined price отсутствуют, UNPRICED;
внутренняя SOT|shots связь не доказывает goals+shots/corners joint model.

```sh
python scripts/small_family_shadow.py --family SHOTS_SOT --as-of 2026-10-13T22:15:00+00:00
python -m unittest discover -s tests -p test_shots_shadow_issue60.py -v
python scripts/verify_release.py
```

6 new synthetic regressions: own parameters/dependent support/mass/mean,
missing/bool/duplicates/contradiction, all-zero unknown thinning,
18-row no-source null report, reuse QC quarantine, goal parameter refusal.
Full local release 1365 tests, 1361 pass + 4 общих PG skips; replay/integrity=true.
Exact OS/Python + actual PostgreSQL mirror/budget CI required; links/exact head
в описании draft PR. CORE src/model_hash/policy_hash/old seals/reports unchanged.
Research-only additions have own source code hash; no model refit/API/keys/
main/production/deploy/money/LIVE. Реальная whole-league season/receipts/
definition/calibration/Stake rules остаются блокерами. Далее FOULS, затем YC.
