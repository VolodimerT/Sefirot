# SEFIROT V3.1: P0 — адаптер исходных наблюдений

Интеграция от 13.10.2026 на базе draft #54,
`9744ba23953b2db101f8af38d5a6cfd8abfbac6c`. Выборочно перенесены адаптер,
CLI и тесты из #23 с уточнениями exact #24
`3707cbf2f2fcafaa773cd82015e2f8537becf74b`. Текущие CORE, query/IANA,
gateway, budget, receipt и проверки целостности сохранены.
Контракт запроса: [FIXTURE_QUERY_CONTRACT_20261010.md](FIXTURE_QUERY_CONTRACT_20261010.md).
P1/P2, refit и новые прогнозные испытания не запускались.
Решение остаётся **KEEP_SHADOW / INSUFFICIENT_REAL_DATA**.

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
| Параметры | Совпадение request/response echo; exact id/ids, league, season, team, status; date/from/to в заявленной IANA-зоне, согласованные offset/date/timestamp | `last/next/round/venue` и неизвестные зоны отклоняются как неподдержанные |
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

Инициализированы оба ограниченных кэша текущего Repository. Проверка
по-прежнему читает все SQL-строки и audit chain; несоответствие колонок
payload обнаруживается до forward replay как `LEDGER_INTEGRITY_FAILED`.
Gateway receipt сохраняется целиком, включая время получения upstream.
Удаление всего каталога архива во время чтения теперь тоже даёт
`ARCHIVE_CHANGED_DURING_READ`; кандидаты при этом не выдаются.
Неверный ISO timestamp, league/season или ошибка чтения CLI завершаются
кодом 2 с фиксированной причиной без traceback и текста исключения.

`packet_reviews` учитывает каждый JSON, `fixture_reviews` — доступные
fixture и объявленные пропуски, `future_packet_exclusions` и
`ledger.future_record_exclusions` — будущие записи. Повреждение любого
входного пакета/журнала даёт общий blocker; локально подходящие строки
становятся `GLOBAL_INPUT_BLOCKER` и не выдаются как кандидаты. Исправленные
результаты, не-FT, другой контекст и HOLDOUT имеют отдельные причины.
Повреждённый JSON, из которого ID извлечь нельзя, учитывается как пакет.
Удалённые до начала чтения наблюдения без внешнего inventory обнаружить нельзя.

## Проверки и достоверные результаты

- **61 тест адаптера**: 55 из #24 и 6 дополнительных регрессий интеграции.
  Все используют вымышленные fixtures из исходных
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
- Дополнительные проверки: удаление архива во время чтения, SQL-метаданные
  постороннего job, текущие gateway receipts и отказ при неверной upstream
  хронологии, безопасные отказы CLI до чтения входа.
- Полный release и PostgreSQL mirror/shared-budget проверяются отдельно.
  Результаты текущего прогона и exact head CI записаны в описании draft PR.
  Исторические отчёты из #23 не копировались как новые результаты.
  Демонстрация и backtest release-check остаются синтетическими регрессиями.
- Окончательные head SHA и матрица Ubuntu/Windows × Python 3.11/3.13
  фиксируются в описании отдельного draft PR после завершения CI.

Canonical src/config/workflows, прежние release/benchmark reports, BASELINE_V1,
DC_DYNAMIC_V1/SOS_LITE_V1 и V3 calibration не изменены. Адаптер находится вне
пакета моделей V3; его SHA учитывается отдельно. Все identities ниже совпадают
с базой #54; они отличаются от исторических identities исходного #23.

| Identity | Значение |
|---|---|
| CORE code_hash | `409c7fdf3cf0f401c9c4ae7fa9a14797a14cdd7d0501c86ed435c355203c0cb3` |
| CORE model_hash | `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee` |
| Policy | `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9` |
| V3 research_hash | `b51a910bcd7e68372dcfd0cebb40eef78363afd8d9dc7e19c86421591966dd3a` |

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
