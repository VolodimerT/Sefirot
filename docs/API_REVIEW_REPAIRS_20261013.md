# Исправления дополнительного ревью №53

База: точная голова №53 `1e3936ca9f48bd5a0568568a6a7e51014cd5db6c`.
Изменения предназначены для отдельного чернового PR поверх №53; main и
рабочие сервисы не менялись. Исправлены R1–R4 из дополнительного ревью.

## Поведение после исправлений

| Проблема | Исправление | Проверка |
| --- | --- | --- |
| R1: токен при redirect | Store client использует NoRedirect, закрывает HTTP error response, проверяет конечный HTTPS URL без userinfo/query/fragment и возвращает фиксированные ошибки. | Настоящий urllib opener с подставным HTTP transport: 301/302/303/307/308 на другой HTTPS/HTTP адрес дают ровно один запрос. Штатный POST и CAS сохранены. |
| R2: ответ на другой запрос | Выборочно перенесён `football_query.py` из точного №24 `3707cbf2`: endpoint/parameters echo, IANA zone, календарь/смещение и fixture scope. Подключён к текущим direct/gateway/collector/server. | Неверные id, timezone, даты, offset и upstream echo отклоняются; invalid local query не открывает transport. Согласованный gateway wrapper не скрывает неправильный upstream. |
| R3: неправильный MCP input | params, name и arguments проверяются до dispatch; пропущенные optional arguments отличаются от явных null/false/0/строки/массива. | JSON-RPC -32602 и нормальный HTTP-ответ при ошибочных параметрах; backend не вызывается. Initialize/discovery/notification и штатные вызовы сохранены. |
| R4: замедление verify | Добавлен bounded cache проверки строки: SHA-256 свежих payload-байтов + все текущие SQL metadata поля. Содержимое payload в cache не удерживается, включая другой регистр имени SQL-колонки. | Повторные SQL-only изменения, payload corruption, orphan и reuse ID после rollback обнаруживаются. Cache ограничен 4096 записей и очищается при close. |

Новая сборка не нормализует и не переподписывает старые packet/receipt/seal.
Legacy archive reader сохранён; новый сбор проверяет предыдущие пакеты до
создания каталога и обращения к API. Неверный новый target отбрасывается до
archive/plan/SQLite. Injectable getter проверяется тем же контрактом. После
query failure дальнейшие попытки останавливаются, уже объявленная cohort
сохраняется целиком. Тестовые fixture echo/timezone изменены только в моках;
исходные бизнес-проверки не убраны.

Сохранены shared reservation/finalization, fail-closed quota, новые enrichment
endpoints, paired gateway/upstream receipts и REGULATION_90 chronology.
При ошибочном upstream echo сервер завершает reservation с FAILURE; повторного
provider I/O нет. Исходный адаптер №23 и другие независимые ветки не перенесены.

## Проверка cache и замер

Каждый verify заново читает полный журнал и все таблицы, проверяет физическую
целостность/FK, цепочку, RECORD hashes и orphan coverage. Cache не сохраняет
journal_ok, разрешения или полный snapshot. Изменение payload или любой SQL
метадаты требует повторной проверки; невалидная строка не попадает в cache.
У cloud snapshot остаётся собственная строгая проверка канонических байтов.

Парный замер на одном синтетическом журнале, 1000 прогнозов, 9 перемешанных
пар с прогретым cache: медиана №53 **581,1 мс**, новая **95,3 мс** — примерно
в **6,1 раза быстрее**. Число SELECT осталось **22/22**. Это замер warm verify
на общей машине; первый проход и строки за пределами cache всё ещё проверяются
полностью. Он не является production SLA.

Исправлен и benchmark harness: архивная версия привязана к своему классу и
использует собственные helper methods. Вызов старого verify на новом объекте
мог бы использовать новый `_verify_current_rows` и сравнить кандидата с собой.
Теперь обе реализации разделяют только одну БД и cache content digests.

## Валидация

- Добавлены **46 Python регрессионных тестов** относительно №53;
  всего **1144**, общий запуск: **1140 passed / 4 skipped** без PostgreSQL DSN.
- Те же четыре SQL-теста отдельно пройдены на настоящем локальном PostgreSQL 16;
  вместе с защитой тестового адреса **5/5**, без пропусков.
- Общий provider budget на другом одноразовом PostgreSQL 16: **10/10**,
  включая 16 одновременных резервирований.
- Node gateway: **41/41** групп, включая четыре новые проверки echo.
- Полный release: exit 0, demo integrity/replay true, 12 синтетических матчей
  backtest / 84 рынка и 49 ретроспективных случаев.
- Семь MODEL_MODULES и Policy совпадают с №53. MODEL hash:
  `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`.
- Новый code_hash:
  `409c7fdf3cf0f401c9c4ae7fa9a14797a14cdd7d0501c86ed435c355203c0cb3`.

Исторические tracked reports после release восстановлены; новые результаты и
замеры находятся вне Git. Старые fit и денежные approvals не перенесены на новый
code_hash. Реальные provider API, deployment, production Supabase и ключи не
использовались. Прибыльность модели этим техническим прогоном не подтверждается.
Результаты exact-head Ubuntu/Windows × Python 3.11/3.13, PostgreSQL mirror и
shared budget записываются в PR после завершения CI.
