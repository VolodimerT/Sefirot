# Единый кандидат CORE 2.4.2 и независимая калибровка

Кандидат объединяет проверенный стек #57–60 с независимым read-only cockpit
#61. Используется существующий draft PR #56; main не меняется. Исходная
RC-ветка #57 остаётся на 22ac74911301d65e831a757222502781842c3bd9.
Точные HEAD и CI links единого кандидата публикуются в описании PR после
проверки. Прежние отдельные CI не заменяют новый CI объединённого дерева.

| Компонент | Включённый точный коммит |
|---|---|
| RC #57 | 22ac74911301d65e831a757222502781842c3bd9 |
| PREMATCH #58 | e32fd7e7a4876005f337314822354bbbabfee2c3 |
| Аудит #59 | d5175c926fad2284c37b69c2d0155763fd34cf70 |
| Угловые #25 | 6275ccd183118623a4ada18a9191b335ea5b7ec9 |
| Удары #65 | d611c086ef71d8aafd1c55e815dcf14097ff9a9e |
| Фолы #66 | d00446015d5e3ddebe88b27d78de42f71b5f8e87 |
| ЖК #67 | 9b363914d9fcab8b0b4a7566d644b80bd7412826 |
| Панель #64 | ee168f8f6284179fc94c96ee5c30e0f9d8b291e3 |

Настоящие parent-связи сохраняют обе ветки. При объединении разрешён только
конфликт исторических инструкций AGENTS.md, с сохранением обеих областей
работы. Исторические источники, seals, approvals и tracked reports прежние.
Семь MODEL_MODULES и Policy сохранены. Общий code_hash включает малые
семейства и равен 56233251fdcffceb0bae3ab8bfe2a5579957ffcfcb6c86c341eac181b97bb2b9.
model_hash: bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee.
policy_hash: 5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9.
Старые forward-планы/approvals не продолжаются на другом code_hash и не
переподписываются. Панель показывает архивные решения с их исходной сборкой.

Проверяется весь release, синтетический lifecycle, Ubuntu/Windows × Python
3.11/3.13 и отдельные PostgreSQL mirror/shared budget. В общем наборе четыре
PostgreSQL skips без DSN показываются явно. История Windows WinError 10053
из отдельного PR #64 остаётся в отчёте; успешный повтор не доказывает причину
того разрыва соединения. Требования auth/PASS и исходные тесты сохранены.

## Проверка настоящих источников

Текущая проверка использует только чтение подключённых management tools,
исходного закрытого checkpoint и сохранённых квитанций. Production SQL,
сервисы, секреты и provider budget не изменяются. Новые API-Football/Stake
запросы не запускаются при неизвестном account status/quota или paused budget.
Доступность Supabase, активный gateway, исторический HTTP 200 и наличие старых
прогнозов не доказывают текущий доступ, полную выборку или независимый HOLDOUT.
Конфиденциальные исходные данные и подробные результаты cloud-инвентаризации
хранятся отдельно от Git. В PR выводятся только безопасные статусы и блокеры.

## Независимая калибровка

Машиночитаемый протокол:
`research/protocols/core242-independent-calibration-v1.json`.
Он фиксирует точную сборку, семь контрактов, порядок TRAIN→CAL→fit→HOLDOUT,
знаменатель, PUSH/VOID, диагностические метрики и запрет настройки по HOLDOUT.
Состояние DRAFT_NOT_REGISTERED: без настоящих league/season/profile/fixture IDs,
исходных квитанций и заранее назначенных окон сбор не начинается. Отсутствующие
поля не заполняются вымышленными матчами. Исторический просмотренный TEST,
старые прогнозы и коррелированные рынки не превращаются в новый OOS.

CAL: исследовательский минимум 60 distinct fixtures, Policy минимум 20 на
точный bin/profile/contract. HOLDOUT: отдельные будущие минимум 60 fixtures
после заморозки calibrator; ни один ID не входит в fit_ids. Coverage target
80% — диагностическая цель, не денежный допуск. Недостаточные/непроверенные
метрики остаются null; quality/profitability/holdout flags остаются false.
Рыночный benchmark требует настоящую проверенную котировку и settlement.
Small families и Builder требуют отдельного evidence, calibration, joint P
и настоящей combined quote; суррогатных P/EV нет.

Read-only команды для существующих оригиналов, без --fit:

```sh
python scripts/calibration_quality_audit.py --db /private/existing-original.sqlite --output /private/new-evidence.json
python scripts/calibration_fit_gate.py --db /private/existing-original.sqlite --output /private/new-preflight.json
```

В этом этапе реальный fit/refit, коллекция новых provider данных и денежный
допуск не выполняются. Пока реальные API, новый HOLDOUT и преимущество модели
не подтверждены, ставки по обновлённому SEFIROT — PASS, stake=0.

## Rollback и ограничения

Этот PR не развёрнут; production rollback не требуется. Для повторного review
доступны исходный frozen RC #57 и каждый отдельный точный HEAD из таблицы.
Не force-push и не откат main: изменение PR — отдельный проверяемый коммит.
Hosted cockpit/HTTPS и реальный Android остаются отдельными зависимостями.
LIVE, догон, autobets, paid provider calls и новый денежный approval запрещены.
