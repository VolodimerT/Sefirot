# Честный evidence audit и будущий HOLDOUT — Issue #59

База: verified #58, draft #62, exact `e32fd7e7a4876005f337314822354bbbabfee2c3`,
12/12 CI jobs. Используется существующий calibration_quality_audit.py,
forward_scorecard, immutable Repository и оригинальные plans/seals.
Новый аудитор или модель с другим источником истины не создаются.

## Что действительно найдено

В текущем workspace нет исходных SQLite/forward-scorecard файлов для новой
реальной оценки. В tracked reports нет original forward-scorecard-v1:
старые demo/backtest/readiness/research отчёты не становятся новым OOS.
Cloud/private store не опрашивался; этот инвентаризационный вывод ограничен
доступным workspace. Никаких новых provider requests, fit/refit или approvals.

Итог команды без source ledger: INSUFFICIENT_REAL_DATA.
TRAIN/CALIBRATION/HOLDOUT не назначены; denominator/coverage/distinct fixtures,
Brier/logloss/ECE/occupancy, market implied benchmark и paired bootstrap=null.
holdout_passed=false, statistical_profitability_proven=false, stake=0.

## Подтверждённые исправления

| Проблема | Исправление |
|---|---|
| bool/float счётчики принимались как integer denominator | Exact int для planned/scored/observations/recomputed |
| Повторные declared contract groups незаметно дедуплицировались | Duplicate group отклоняется |
| HTTP status 200.0 принимался архивом и forward receipt | Только исходный integer 200 |
| NS target с заполненным fulltime score принимался normalizer | Заданный счёт/неверный container отклоняется до sports capture |

Числа fulltime прежнего synthetic NS fixture не участвовали в goal P, но
такой источник недопустим. Старые frozen файлы issue58 сохранены побайтно.
Новый valid scenario хранится отдельно в prematch_issue59_source_v2; он имеет
null fulltime, отдельный hash и использует тот же existing PREMATCH путь.
Два legacy positive test inputs теперь явно задают отсутствующий NS score;
их assertions не изменены. Negative известный NS result проверяется отдельно.

Три non-model source modules меняют code_hash; все семь MODEL_MODULES/Policy
и старые reports/seals/fit/approvals сохранены. Никакого re-sign/recalculation.

## Команды

```sh
python scripts/calibration_quality_audit.py --output /absolute/new-no-source.json
python scripts/calibration_quality_audit.py --db /absolute/existing.sqlite --at 2026-10-13T21:15:00+00:00 --output /absolute/new-evidence.json
python scripts/calibration_quality_audit.py original-scorecard.json --output /absolute/new-descriptive-audit.json
python -m unittest discover -s tests -p test_evidence_audit_issue59.py -v
python scripts/verify_release.py
```

Output создаётся эксклюзивно; original input/ledger не переписывается.
Original inventory держит один read-only snapshot, проверяет ledger, читает
plans/split assignments/calibrators и создаёт existing scorecards из исходных
records без пересчёта прогнозов. Declared local denominator и unscorable/VOID
показываются отдельно от verified real coverage. Local hashes не удостоверяют
провайдера; даже хороший локальный журнал не снимает origin blocker.

Legacy positional scorecard mode сохраняет только descriptive diagnostics
входного self-attested checksum. Это не новый эмпирический сертификат.
Рыночный benchmark остаётся null без настоящей verified quote/rules; odds,
closing price и сыгравшие ставки не домысливаются.

18 новых regressions: strict counters/groups/status, NS result, source cutoff,
missing/corrupt/absent read-only DB, all-expected-fixture denominator, original
unscored cohort, cross-cohort/duplicate IDs, strict time windows, post-kickoff
registration, frozen fit content/date/fit IDs, viewed TEST role, PUSH/VOID,
versioned source fixture. Existing auditor продолжает считать Brier/logloss/
ECE occupancy и paired bootstrap по fixture/day; несколько рынков одного
матча не становятся независимыми наблюдениями.

Полный локальный release прошёл: 1331 tests, 1327 pass + 4 общих PostgreSQL skips.
Actual mirror/budget отдельно обязательны в CI. Окончательный exact SHA,
количество tests и все CI links записываются в описании draft PR после проверки.

## Prospective plan и минимальный денежный допуск

План является DRAFT_NOT_REGISTERED_OR_COLLECTING: fixture IDs, лиги, сезоны,
профили, зарегистрированные окна и даты пока null. Нельзя задним числом
объявить ранее просмотренные 8 игр/312 строк или TEST независимым HOLDOUT.
План сначала требует разрешённый verified source + полный league denominator,
original UTC publication/receipt/revision и exact IDs; затем фиксируются
TRAIN → CALIBRATION → HOLDOUT, все контракты и признаки до получения исходов.
Fit должен существовать до регистрации HOLDOUT и не включать его fixtures.
Требования Policy: 20 distinct fixtures на exact calibration bin, минимум
60 distinct HOLDOUT fixtures; research coverage target 80%, не денежный допуск.

Historical modeled EV vs realized yield — историческая гипотеза.
EV зависит от качества P, цены и расчёта; yield — от действительно записанных
рассчитанных tickets, PUSH/VOID и turnover denominator. Коррелированные линии,
viewed TEST и недостоверные цены/источники не доказывают новый edge.
Новых доходности, цен закрытия или пользовательских ticket данных нет.

Минимальный денежный допуск требует independently verified permitted sources,
нового нетронутого достаточного HOLDOUT, проверенной calibration/coherence/
uncertainty и контекста, действительных Stake quote/settlement/freshness,
закрытых tactical/death-test/data/price/portfolio gates и отдельного exact-build
Policy approval владельца. Одних sample minima или зелёного CI недостаточно.
Этот этап не предоставляет ни одного из отсутствующих разрешений.

Следующий этап #60: последовательные SHADOW family increments с настоящими
source blockers/null P/EV, переиспользуя имеющуюся corners/QC инфраструктуру.
#61 — read-only phone prototype; actual endpoints пока не подключены.

Identity: code_hash `43e55e179240cbe42ae0d0973eebda6934ece715df52c4c31d8cb9d4e7bddba1`, model_hash `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`, policy_hash `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`.
