# SEFIROT V3.1: P0 — адаптер исходных наблюдений

Задание: `SEFIROT_TASK_AUDIT_V3_1_2026-10-09.md` и
`SEFIROT_SOL_ASTRA_NEXT_TASK_2026-10-09.txt`, прочитанные целиком.
База: draft PR #21, commit `121a580143e8b4c0d98669bb5c0a0b7dbcfe317b`.
Выполнен только программный этап P0. P1/P2, refit и новые прогнозные испытания
не запускались. Решение остаётся **KEEP_SHADOW / INSUFFICIENT_REAL_DATA**.

## Проблема и изменение

V3 принимал объявленные исследовательские строки, но не имел адаптера их
привязки к исходному sports archive и forward SQLite. Поле `receipt_sha`
и самосогласованный JSON не подтверждают получение данных от поставщика.
Локальная цепочка audit_logs тоже не является внешней подписью или независимой
меткой времени: владелец всех исходных байтов может пересоздать её.

Добавлены `research/source_adapter_v3.py`, отдельный read-only CLI и тесты
на исходных схемах репозитория. Адаптер возвращает типизированные
`candidate_rows`, связи с пакетами и полный разбор исключений. Кандидаты
обозначены `STRUCTURALLY_VALID_EXTERNAL_UNVERIFIED`; они **не допущены к
обучению**. `training_rows=[]`, `training_allowed=false`,
`source_verification=UNVERIFIED_EXTERNAL_ORIGIN` при любом входе. Программного
переключателя `verified=true`, который разрешает обучение, нет.

Реальные исходные архив и SQLite в доступном рабочем дереве не найдены и не
предоставлены. Старые сводки, в том числе ранее просмотренные TEST/forward
результаты, не превращались в исходные записи и не использовались как новая
выборка. Реально допущенных TRAIN/HOLDOUT матчей — **0**. Новый API-запрос
не выполнялся; текущий статус провайдера этим этапом не установлен.

## Проверяемые связи

| Вход | Локальные проверки | Ограничение |
|---|---|---|
| Archive JSON | Каноническое имя `digest(packet).json`, payload SHA, схема/host/provider/endpoint, HTTP 200, errors/count/paging, отсутствие цен | Файл и receipt могут быть сфабрикованы вместе |
| Параметры | Совпадение request/response echo; exact id/ids, league, season, team, status; UTC date/from/to | `last/next/round/venue` и не-UTC timezone отклоняются как неподдержанные, а не игнорируются |
| Fixture | Числовые fixture/team/league IDs, разные команды, season, согласованные date/timestamp, неизменная идентичность | Это проверка заявленной идентичности; реестр поставщика не запрашивается |
| История FT | Только regulation FT; один счёт, первый FT receipt, повторные/одновременные наблюдения, cutoff, 90 минут, давность ≤730 дней | Точный финальный свисток неизвестен; `finished_at` — верхняя граница по первому receipt |
| Профиль | Явная операторская декларация; совпадение с исходным планом для всей лиги | MEN/WOMEN/RESERVE/LOWER не угадываются по названию команды; декларация не подтверждает официальную классификацию |
| SQLite | Schema v2, quick_check/FK, полная audit-chain/RECORD, hash forward job, совпадение payload/storage columns и времени | Целостность всего снимка не доказывает его внешний источник |
| Forward plan | Selection packet/receipt, исходные fixture/team IDs, league/season/profile, prematch cutoff и split assignment | Старый code_hash не переподписывается; model_hash должен быть совместимым |
| Capture | Original seal, plan/pool/model/policy, chronology, packet receipts, replay исходного sports export | Вероятности не пересчитываются и не изменяются; replay поддержан для текущей canonical Policy |
| Result | Исходный result-source job/plan, raw fixture/team IDs, счёт и receipt, первое FT-наблюдение | Отсутствующая связь или revision означает отказ |
| HOLDOUT | Существующие HOLDOUT assignments исключаются, в том числе вне forward-plan | Новая выборка/разделение этим адаптером не регистрируется |

Допустимая история охватывает объявленный сезон и два предыдущих сезона,
как в существующем V3 `checked_rows`. Более старые строки и другой контекст
попадают в явные причины отказа. Имена команд сохраняются в метаданных,
но ключи V3 — точные `api-football:team:<ID>`: одинаковое имя не объединяет
разные IDs, переименование не создаёт новую команду.

В legacy packet нет доказательства несинтетического происхождения.
`candidate_rows.synthetic=false` обеспечивает совместимость формы строки с
legacy sports-входом; это не аттестация реальности. Запрет обучения и
`source_verification` обязательны. Кандидаты не подключены к V3 benchmark/fit.

## Read-only и воспроизведение

```sh
python scripts/prediction_edge_source_adapter.py \
  --archive /path/to/original/archive \
  --database /path/to/offline-forward.sqlite \
  --cutoff 2026-10-09T20:00:00+00:00 \
  --league-id 9 --season 2026 --profile LOWER
```

Контекст в команде — **образец**, не выбранная реальная лига или cohort.
Использовать исходные декларации своего набора. JSON выдаётся в stdout:
адаптер не создаёт каталог, БД или выходной файл, не выполняет сеть и не
получает credentials. Не изменяет seals, результаты, роли, деньги и Policy.

SQLite открывается `mode=ro&immutable=1`, с `query_only`, в read transaction.
Нужен закрытый checkpointed снимок: наличие `-wal`, `-shm` или `-journal`
даёт `LEDGER_REQUIRES_OFFLINE_SNAPSHOT`. Адаптер сам не выполняет checkpoint,
копирование или миграцию рабочего журнала. SHA снимка и файлов архива
сверяются при чтении; изменение входа блокирует весь результат.

`packet_reviews` учитывает каждый JSON, `fixture_reviews` — доступные
fixture и объявленные пропуски, `future_packet_exclusions` и
`ledger.future_record_exclusions` — будущие записи. Повреждение любого
входного пакета/журнала даёт общий blocker; локально подходящие строки
становятся `GLOBAL_INPUT_BLOCKER` и не выдаются как кандидаты. Исправленные
результаты, не-FT, другой контекст и HOLDOUT имеют отдельные причины.
Повреждённый JSON, из которого ID извлечь нельзя, учитывается как пакет.
Удалённые до начала чтения наблюдения без внешнего inventory обнаружить нельзя.

## Проверки и достоверные результаты

- **52 новых теста**, все используют вымышленные fixtures из исходных
  `test_operations_upgrade` и настоящие схемы Repository/forward services.
  Они не являются реальными футбольными экспериментами.
- Положительный путь: оригинальные plan → archive → capture → result,
  read-only replay, равенство байтов архива/SQLite и исходных seals до/после.
- Контрпримеры: SHA tampering, rehash со старым именем, wrong id/league/season,
  changed identity/kickoff, дубликат, revision, одновременный конфликт,
  future/premature receipt, missing source, unknown provider, prices,
  unsupported query semantics, corrupt/empty SQLite и WAL/journal.
- Самосогласованные локальные JSON/цепочки не получают внешнего допуска.
  Подмена plan/capture/result, даже с новым правильным local hash/RECORD,
  отклоняется по независимой связи с исходными пакетами.
- Полный локальный `python scripts/verify_release.py`: **768/768**, без
  skipped; demo replay/integrity=true. Новый отдельный отчёт:
  `reports/PREDICTION_EDGE_V3_1_ADAPTER_RELEASE.json`. Демонстрация и backtest
  release-check остаются синтетическими инженерными регрессиями.
- Окончательные head SHA и матрица Ubuntu/Windows × Python 3.11/3.13
  фиксируются в описании отдельного draft PR после завершения CI.

Canonical src/config/workflows, прежние release/benchmark reports, BASELINE_V1,
DC_DYNAMIC_V1/SOS_LITE_V1 и V3 calibration не изменены. Адаптер находится вне
пакета моделей V3; его SHA учитывается отдельно, research_hash прежний.

| Identity | Значение |
|---|---|
| CORE code_hash | `5bde1cbf96efab4bfd3890c4802f86a14f193564bdd047e4db78e1fc4f6fe95f` |
| CORE model_hash | `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617` |
| Policy | `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9` |
| V3 research_hash | `f435680df74557f305ebc94a1677c5409538b8c92f76cc62362e55a21ffbb263` |

## Блокер и единственный следующий шаг

Получить **исходный sports archive и offline SQLite snapshot с проверяемым
внешним происхождением**, а также их исходный league/profile/season/cutoff,
и пропустить их через этот адаптер. До этого дорогие TRAIN, HOLDOUT, refit
и P1/P2 не запускать. Внешний admission/attestation gate остаётся отдельной
нерешённой задачей; само добавление адаптера не делает источник подлинным.

Сравнение моделей, Brier/log loss на новых реальных матчах, преимущество над
линией, EV/CLV, полезность ARENA и вероятности Builder этим P0 **не измерены**.
Подтверждённый результат этапа — воспроизводимые инженерные проверки входа,
а не увеличение прогнозной точности или прибыльности.
