# CORE 2.4.2 release candidate — Issue #57

Единый кандидат продолжает существующий draft PR №56. Его исходный head
`fbab85d0d0666ec593cb739d3a81f357279c59ea` уже включает №53 → №54 → №55 → №56.
Исправления RC находятся в отдельной ветке `release/core242-rc-issue57-20261013`.
PR остаётся draft; его интеграционная база — main, слияние не выполняется.
Окончательный RC SHA, tree и ссылки на CI записываются в описании №56 и
проверяемом отчёте после публикации. Для локальной проверки: `git rev-parse HEAD`.

## История и область

| PR | Проверенный исходный SHA | Включение |
|---|---|---|
| 53 | `1e3936ca9f48bd5a0568568a6a7e51014cd5db6c` | CORE 2.4.2 и audit №52; ancestor 54 |
| 54 | `9744ba23953b2db101f8af38d5a6cfd8abfbac6c` | API/MCP/echo/IANA и bounded integrity cache; ancestor 55 |
| 55 | `5b11061acc9b22fce59eaea313f3c45fde4f2808` | Исходный offline source adapter; ancestor 56 |
| 56 | `fbab85d0d0666ec593cb739d3a81f357279c59ea` | Receipt-bound situation, HTTP/MCP/queue, reviewable SQL/relay |

Текущие открытые головы, включённые по git ancestry:
15, 16, 17, 18, 19, 21, 22, 35, 37, 38, 39, 41, 42, 43, 45, 46, 47,
49, 50, 51, 52, 53, 54, 55, 56. Ancestry подтверждает историю, но сама по
себе не доказывает сохранение каждого прежнего эффекта: проверен итоговый diff.

Не являются ancestors текущего кандидата: 8, 9, 11, 12, 13, 14, 20, 23,
24, 25, 26, 27, 28, 30, 32, 34, 36, 40, 44. Эффекты 23/24 и 32 перенесены
выборочно в 54/55/56; это не полное слияние их старых веток. ARENA, отдельный
corners prototype, FootyStats adapter, autosave/private archive и некоторые
старые status/enrichment варианты остаются отдельными. №30 и №32 — параллельные
ветки от №22; №34 предшествует №36. Не переносить весь стек повторно.

## Независимая повторная проверка и подтверждённые дефекты

Проверялся реальный итоговый код, а не прежний статус CI. Отдельного внешнего
аудитора не было. Минимальные исправления выполнены отдельными коммитами.

| Приоритет | Подтверждённый дефект | Исправление |
|---|---|---|
| Высокий | CAS checkpoint принимал активный WAL; raw SQLite мог не содержать новые committed записи. | До транспорта требуется закрытый snapshot без WAL/SHM/journal; проверяются ровно сохраняемые байты и изменение файла. |
| Средний | Правильные заголовок и gzip checksum позволяли restore создать повреждённую БД. | Полная read-only проверка snapshot перед созданием целевого файла/каталога. |
| Средний | Пустая таблица audit без hash давала verify=true; с записью — IndexError. Потеря id PK также не обнаруживалась. | Свежая проверка обязательных колонок и единственного id PK в verify/cloud snapshot; один общий column mapping. |
| Низкий | Ошибка первого PRAGMA чтения могла оставить SQLite connection открытым. | Constructor закрывает принадлежащее ему соединение при ошибке. |

7 новых schema/resource/CLI регрессий и 4 CAS-регрессии. Исправления не
меняют данные, миграцию SQLite, уравнения вероятностей или Policy.
Вычитаны SQLite verify/cache/metadata, cloud mirror, HTTP redirects/credentials,
fixture ID/timezone, gateway reserve/finish, MCP, SQL privileges, situation HOLD,
receipt/lease и CLI. Негативные тесты выполняются на фиктивных данных/токенах.

## Проверки и воспроизведение

Локальный полный release: 1293 теста — 1289 passed, 4 PostgreSQL skipped.
Четыре проверки БД выполняются отдельно; mirror — 5/5 без пропусков
(включая ограничение тестового адреса), shared budget — 10/10, 16 callers.
Demo integrity/replay=true, synthetic backtest 12 fixtures/84 markets,
audit 49 случаев. Node/PGlite проверяет реальный offline SQL/relay/worker/restart.

```sh
npm ci --ignore-scripts --no-audit --no-fund
python -m pip install '.[sync]'
python scripts/verify_release.py
python sefirot.py --help
python sefirot.py --db /path/to/owned/offline.sqlite verify
python scripts/benchmark_integrity_v5.py --baseline-ref fbab85d0d0666ec593cb739d3a81f357279c59ea --size 1000 --pairs 9 --output /absolute/new-benchmark.json
```

Отсутствующий ledger для verify даёт exit 2 и не создаётся. Полный release
создаёт синтетические отчёты; прежние tracked reports после проверки восстановлены.
Обязательный CI: Ubuntu/Windows × Python 3.11/3.13, PostgreSQL mirror/shared
budget. Все обязательные jobs должны быть зелёными на точном RC HEAD.
Skips общего прогона не считаются выполненными PostgreSQL-тестами.

Schema check сохраняет 22 record SELECT на каждом verify. Парный warm benchmark
на 1000 синтетических prediction: 109,385 → 110,792 мс, median delta +1,452 мс,
9 пар на одном общем хосте. Это плата за новую структурную проверку; production
SLO не доказан. Ни journal_ok, ни permissions, ни полные records не кэшируются.

## Identity и сохранённые факты

| Поле | Значение |
|---|---|
| version | `2.4.2` |
| code_hash RC | `a40ed1d0e29737e004e607fdcf483f6624705ae5ff2ef255877fead8468e0853` |
| прежний code_hash №56 | `409c7fdf3cf0f401c9c4ae7fa9a14797a14cdd7d0501c86ed435c355203c0cb3` |
| model_hash | `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee` |
| policy_hash | `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9` |

Все семь MODEL_MODULES/Policy побайтно прежние. Non-model code_hash изменён
из-за подтверждённых исправлений. Прежние seals/ledger/approvals/reports не
переписаны; старый approval не переносится на новую сборку автоматически.
Source/readiness и original PASS не повышаются до BET, live/execution закрыты.

## Риски, rollback и production blockers

API-Football: текущий доступ NOT_VERIFIED; последний документированный отказ
account suspended — 06.10.2026, это не доказательство текущего статуса.
Stake odds, фактическая версия/auth gateway и частный Supabase store сейчас
NOT_VERIFIED. Shared budget доказан локально/CI, deployment не проверен.
Настоящей source attestation, новой независимой HOLDOUT и денежного допуска нет.
Real un-attested situation всегда HOLD. Старые generic mutating queue jobs
сохраняют прежнюю retry семантику; source/quote/chat e2e — следующий #58.

SQL/relay templates не применены в облаке; DEPLOYED_AUTH пуст. Hosted Supabase,
Deno/PostgreSQL 17, полный cold/warm production путь не проверены. Ранее
описанный runner мог обращаться к провайдеру при старте: его не запускать
и не redeploy без отдельной авторизации. Ни secrets, ни paid requests,
deployment, main, денежные ставки или пользовательские данные не менялись.

Rollback: RC не установлен в production, поэтому рабочую систему откатывать
не требуется. Для сравнения открыть новый isolated checkout старого №56 SHA
или main `d09a8af22f0dec8c84bc203d468b913b46fc2f94`. Не сбрасывать main/общую
ветку и не перезаписывать текущий ledger; исследовать только закрытую копию.
Старые seals читать их исходной сборкой, автоматического re-sign/refit нет.

После зелёного exact-head CI и фиксации отчёта #57 — переход к #58, затем #59.
#60/#61 выполняются после их зависимостей, с сохранением перечисленных запретов.
