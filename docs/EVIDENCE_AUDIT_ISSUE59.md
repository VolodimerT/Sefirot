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

## Противоречивый PREMATCH elapsed, 14.10.2026

На проверенном #63 `5aa05f35639b80df44a4a2a1ee90f89a0a3ad730`
статус NS вместе с elapsed=25 и будущим kickoff принимали selector,
normalize_sports, forward-plan и export_sports. Это противоречие исходных
данных: NS не может одновременно означать уже сыгранные минуты.

Одна validate_prematch_state теперь используется selector и planner;
normalizer и archive export используют selector. Optional elapsed может
быть отсутствующим/null или точным integer 0. Положительные/отрицательные
минуты, bool, float, строка и неверный контейнер отклоняются. Неизвестное
значение не заменяется нулём. Проверки score/fulltime сохранены и также
переиспользуются planner, без копирования противоречивой логики.

5 новых регрессий, всего 28 профильных тестов: все пути отказа, типы,
valid unknown/zero без изменения input, атомарный отказ всего plan batch
до split/job records, сохранение сырых archive bytes при отказе экспорта.
Это тестовые квитанции, не реальные provider calls или модельное обучение.

Меняются два non-model SRC файла football_provider.py и forward.py,
поэтому новые CORE code_hash фиксируются явно для каждого HEAD. Все
7 MODEL_MODULES и Policy, V3 модель, старые source/seals/fit/approvals/reports
не меняются и не переподписываются. Старый forward plan нельзя автоматически
продолжать на другой code_hash; исторический read-only audit остаётся доступен.
Main и фиксированный RC #57 не переключаются. Полный CI обязателен на
каждой обновлённой зависимой draft ветке #63/#25/#65/#66/#67/#64.
Actual mirror/budget отдельно обязательны в CI. Окончательный exact SHA,
количество tests и все CI links записываются в описании draft PR после проверки.

## Исходные prediction IDs и frozen build, 14.10.2026

На проверенном #63 `dc79c938536d699571a3e0def8e9c4039ffa5233`
descriptive-аудитор принимал SCORED fixtures/observations без prediction_id,
либо один prediction_id у двух разных матчей. Он также принимал model_hash
как bool; frozen_build в виде list приводил к необработанному AttributeError.
Это дефекты проверки происхождения, а не доказательство реальной ставки:
денежные/holdout/profitability flags уже оставались false.

Теперь каждый оценённый матч требует непустой строковый ID исходного seal.
ID уникален между fixtures; разные рынки одного матча сохраняют общий ID.
Неоценённый матч без capture сохраняет null и входит в полный denominator.
frozen_build требует объект и исходные SHA256 code/model/policy_hash;
calibrator_id может быть null либо непустой строковой ссылкой. Неверные
формы возвращают ValueError и короткую ошибку CLI, без traceback, нового
output и изменения входного scorecard. Никакой подстановки текущей сборки
в исторический scorecard нет; local hash не удостоверяет внешнего провайдера.

Пять новых регрессий, всего 33 профильных теста; прежние проверки когорт,
receipt chronology и PREMATCH NS/elapsed сохранены. Изменяются только
auditor script, профильные тесты и документация. Все SRC/MODEL_MODULES,
Policy, текущие CORE code_hash и старые reports/seals/receipts остаются
прежними; SHA256 самого auditor script фиксируется отдельно. Перенос
в существующий стек #63/#25/#65/#66/#67/#64 требует полного exact-head CI.

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

Историческая identity исходного этапа #59: code_hash `43e55e179240cbe42ae0d0973eebda6934ece715df52c4c31d8cb9d4e7bddba1`.
После исправления NS/elapsed текущий code_hash #63/#64 — `5fddf9b1d0d1f7f02b78d5de3baa2da0b1cf32569fa772750d5328f58c80a11b`,
а #25/#65/#66/#67 — `56233251fdcffceb0bae3ab8bfe2a5579957ffcfcb6c86c341eac181b97bb2b9`.
Общие model_hash `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`
и policy_hash `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9` прежние.
Новые точные commit SHA и CI links фиксируются в описаниях draft PR.
