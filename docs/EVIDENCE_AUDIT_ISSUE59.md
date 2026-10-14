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

## Повторная проверка когорт и frozen fit, 14.10.2026

На исходном #63 `b1961710bcb0634e40e013260a4c38d963bad1a4` проверка
TRAIN→HOLDOUT не выполнялась, если CALIBRATION отсутствовала. Подписанные
локальным content hash fit_ids в виде строки/словаря или с повторными ID
также не давали ошибки. Такой checksum не доказывает пригодность данных.

Теперь порядок проверяется для каждой пары объявленных этапов. Отсутствие
другой когорты не исключает сравнение существующих временных окон.
fit_ids требуют непустой список уникальных непустых строк. Неверные
контейнеры, ID, timestamps и формы плана/fit возвращают явные ошибки;
исходные записи не меняются. Аудитор настоящего локального журнала с
корректной hash-цепочкой, но неверным fit_ids, возвращает QUARANTINED.

Добавлены 5 регрессий: временной порядок без промежуточной когорты,
формат/уникальность fit IDs, повреждённые cohort/fit и read-only проверка
hash-bound SQLite. Старые 18 тестов сохранены; всего 23 профильные теста.
Это синтетические отрицательные проверки, не реальные TRAIN/CAL/HOLDOUT,
не обучение и не доказательство качества модели. Метрики без независимого
происхождения остаются null, holdout/profitability=false. CORE code_hash,
model_hash/policy_hash и старые source/seals/reports не меняются; SHA256
самого auditor script меняется явно.

Исправление переносится последовательно в существующие зависимые draft
PR #25→#65→#66→#67 и независимый #64; ветка main и RC #57 неизменны.
Точные коммиты и полный OS/Python/PostgreSQL CI фиксируются в PR и отчёте.
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
