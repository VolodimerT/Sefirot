# Явное ограничение сценария: аудит 05.10.2026

Рабочая ветка `feature/stability-reset-20261005`, draft PR #11.
Продолжение первого шага стабилизации; VERSION 2.4.2, BASELINE_V1/STRICT.

## Основание и границы исправления

Новый DAILY AUDIT описывает переход от спортивного вывода «избегать
результата» к Builder с результатной ногой. Исходных immutable прогнозов
и API receipts для этого эпизода здесь нет: воспроизводимость именно
того решения и диагноз ошибки вероятностной модели не подтверждены.
Проверка текущего кода показала конкретный пробел: явный спортивный
запрет не имел структурного контракта, общего для admission и Builder.

Исправляется только этот пробел. Порог «рынок должен выиграть во всех
правдоподобных счетах» не вводится: у разумной ставки есть проигрышные
ветви. Низкая вероятность результата, близость сил или прошедший счёт
сами по себе не порождают запрет. Численные пороги по просмотренному
аудиту не подбираются. Новые команды, модель, парлай admission и ставки
на Builder не добавлены.

## Контракт до цены

Используется существующая sports evidence запись `matchup_signal`,
`kind=INFERENCE`, с источником и FACT premises. Только явная
`value.selection_constraint` включает ограничение:

```json
{
  "status": "CONSISTENT",
  "selection_constraint": {"avoid_result": true}
}
```

Это фрагмент `value`, не полный sports packet. Полная запись сохраняет
существующие id/source_id, published_at/received_at/observed_at,
critical и непустой supports. Она поступает в `capture` до цены и kickoff.
`CONSISTENT` означает отсутствие существующего глобального конфликта
matchup с моделью; локальный запрет результатных рынков остаётся активным.
`CONFLICT` по-прежнему блокирует весь прогноз существующим gate.

Текст чата автоматически не распознаётся. API-коллектор не придумывает
такой вывод из баланса сил. Интеграция должна явно записать inference
по полученным спортивным FACT; коэффициенты и результат не являются
основанием. Внутри selection_constraint разрешён только avoid_result
с точным boolean true; false, 1, строки, null, неизвестные поля отвергаются.
Снятие запрета требует отдельной новой sports revision, а не false в
перепроверке или изменения старого seal.

Источник inference должен быть enabled/reliable/fresh по действующей
Policy. Все supports должны быть активными reliable/fresh FACT с
разрешённым конфликтом значений; superseded записи не подходят.
Недостаток доказательств даёт SCENARIO_CONSTRAINT_UNVERIFIED и общий
PASS. Уже объявленный запрет при этом сохраняется, а не исчезает.

## Порядок применения

| Этап | Поведение |
|---|---|
| prepare/capture | Сохраняет avoid_result, evidence IDs и hash содержания premises в scenario; вероятности не меняет |
| readiness | Показывает SCENARIO_MARKET_CONFLICT до запроса цены |
| decide | Заново читает запрет из sealed sports, не доверяет очищенной метке кандидата; блокирует результатный рынок до ранжирования |
| final recheck | Добавление/снятие запрета или изменение FACT premises требует SPORTS_CHANGED_RECALCULATE и нового seal; обновлённые IDs/время при прежнем содержании разрешены |
| decision card | Конфликтующий рынок остаётся в alternatives, но не становится research candidate; обновление цены запрет не устраняет |
| 50-contract grid | Сохраняет весь фиксированный знаменатель; результатные контракты помечены BLOCKED_BY_SCENARIO |
| history comparison | Передаёт selection_issues и статус, не теряет запрет при sensitivity diagnostic |
| 14 Builder | Любая результатная нога помечает всё сочетание BLOCKED_BY_SCENARIO; D/stake=0 остаются обязательными |
| compare-builder | Исключает конфликтующие одиночки из best_single_diagnostic даже при высоком raw EV; joint цена и превосходство Builder остаются неизвестными |

Результатные семьи: 1X2, DOUBLE_CHANCE, DNB, HANDICAP. TOTAL, BTTS и
TEAM_TOTAL не блокируются этим конкретным запретом. Это не автоматический
допуск голевых рынков: все остальные sporting/calibration/holdout/policy
и risk gates сохраняются. Числа заблокированных research rows остаются
диагностикой, не рекомендацией.

## Проверка и identity

14 новых regression tests проверяют controlled BET→PASS при положительном
EV, сохранение допуска TOTAL, изменение/снятие ограничения, обновление
support IDs, изменение optional context premise, malformed fields,
stale/unreliable/superseded/conflicting support, read-only readiness,
весь знаменатель сеток, API single ranking, history propagation и
переподписанную подмену research artifact. Обычная проигрышная ветвь
остаётся допустимой; raw/base/stress и score model совпадают до/после
добавления restriction.

Все семь MODEL_MODULES побайтно сохранены. Model hash прежний:
`46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`.
Новая admission/build identity:
`051751bc5336f122a412753acc71347cde9f46eb237bbe26de5f16f510c3ecd0`.
Старые seals/approvals не переподписывать; replay на исходной сборке.
Точный итог полной сборки записан в reports/RELEASE_CHECK.json.

Полный локальный release: 491/491 тестов, demo/replay/integrity успешны
на Python 3.12.14/Linux. Из 15 новых тестов этого продолжения 14 проверяют
restriction, один — legacy help с принудительным CP1252 stdout. Первый
опубликованный stability head прошёл Ubuntu, но выявил две Windows ошибки:
кириллица legacy help и открытое соединение в corruption test. Wrappers
теперь конфигурируют UTF-8 и для --legacy; тест явно закрывает SQLite
после transaction. Удалённый CI финального head сверять отдельно.

## Следующие проверки по аудиту

EXTERNAL TIP + SEFIROT FILTER учитывать отдельно от собственного
price-blind прогноза; один отфильтрованный успех не оценивает edge модели.
Без оригинальных seals/receipts финансовый аудит остаётся reported/unverified
и не попадает в calibration или HOLDOUT. Ретроспективные «model miss»,
«market mismatch» и «Builder dependency miss» требуют проверки original
inputs; диагноз не назначать только по результату.

Парлай/Builder денежный допуск остаётся неподдержанным. Нужны новая
независимая API-выборка, исходная joint цена, calibration и заранее
проверенная процедура отбора. Следующий baseline/DC протокол остаётся
PROPOSED/NOT RUN из STABILITY_RESET_20261005.md. Main не сливать.
