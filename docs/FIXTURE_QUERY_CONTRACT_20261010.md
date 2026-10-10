# Контракт fixture query / timezone, 10.10.2026

Новый сбор теперь проверяет фактический ответ `/fixtures` до архивирования
и создания forward-плана. Исправление продолжает draft #23 от
`67e10930257b4df0af42f3dcfd086a8f5d9c0f05`; модель и денежная Policy прежние.

## Подтверждённая ошибка

До исправления Python direct/gateway clients и коллектор проверяли
идентичность receipt и gateway wrapper, но не provider `data.parameters`.
Wrapper возвращает переданный запрос; он не подтверждает применение
параметров upstream. Так согласованный wrapper мог скрыть fallback timezone.

Календарная проверка target в коллекторе выполнялась после записи пакета.
Не соответствующий запрошенному дню ответ мог остаться в новом архиве,
хотя дальнейшее создание прогнозов завершалось отказом.

В исходном P0 адаптере были поддержаны только UTC/Etc/UTC. Даже корректный
ответ с `Europe/Kyiv`, используемым коллектором по умолчанию, не проходил
replay семантики запроса. Это ограничение заменено проверкой IANA.

Код текущего и опубликованного старого `provider_transport.py` кодирует
переданные параметры через `urlencode`; silent timezone rewrite там не
обнаружен. Старые receipt/payload без записи фактического upstream обмена
не устанавливают причину исторического расхождения. Ошибка поставщика,
неподдержанная им timezone или дефект внешнего транспорта не доказаны.

## Изменения

`src/sefirot/football_query.py` предоставляет общий read-only контракт:

| Проверка | Поведение |
|---|---|
| Endpoint echo | Требуется `get=fixtures` |
| Parameters echo | Точные ключи и значения; целое/string допускаются при одинаковом строковом представлении |
| Недопустимый echo | Bool, composites, missing/extra keys и подмена timezone отклоняются |
| Timezone | Локальный IANA preflight; неизвестная зона отклоняется до network/credential lookup |
| Date/from/to | Строгий ISO date, включительные границы, `from <= to`; дата определяется в запрошенной зоне |
| Kickoff offset | Смещение ISO timestamp должно соответствовать IANA для данного UTC instant; timezone field, если есть, совпадает с запросом |
| Fixture scope | Точные id/ids, league, season, team и status, если заданы |
| Отказы | Фиксированные коды без upstream текста или credentials |

Direct client и Python gateway выполняют preflight и проверку ответа.
Server template также проверяет endpoint/parameters echo до success wrapper;
полная проверка календаря/строк остаётся в Python. Изменение template
проверено offline, deployment не выполнялся.

Коллектор проверяет echo и scope ещё раз для injectable getter, до
`archive_packets`, plan или SQLite. Query failure останавливает дальнейшие
сетевые попытки; уже объявленная cohort сохраняется целиком. Плохой prior
archive отклоняется до network и создания нового каталога; исходный не меняется.

Адаптер использует тот же echo/calendar checker. `last/next/round/venue`
остаются неподдержанными для его source replay; FT query scope, cutoff,
SQLite bindings, HOLDOUT exclusion и external-origin gate сохранены.

## Совместимость и границы

- Legacy `sports_archive.validate_packet/read_archive` оставлены для
  воспроизведения старых записей; integrity reader не является новым admission.
- Receipt, payload, даты и seals не нормализуются и не переподписываются.
- Default session timezone `Europe/Kyiv` сохраняется. Автоматического
  повторения запроса в UTC или замены на `Europe/Kiev` нет.
- Наличие IANA зоны локально не подтверждает её поддержку поставщиком.
  Его список timezone и реальный запрос/ответ ещё нужно проверить после
  возобновления доступа в новой заранее назначенной ограниченной сессии.
- Семь MODEL_MODULES, BASELINE_V1/STRICT, Policy и V3 model modules
  побайтно сохранены. Transport/source changes меняют CORE code_hash;
  старые seals воспроизводятся на архивной сборке, а не переподписываются.
- `UNVERIFIED_EXTERNAL_ORIGIN`, `training_rows=[]`, `KEEP_SHADOW` сохраняются.
  Ни обучения, sporting API, изменения cloud/keys, ни main merge не было.

## Проверки

Добавлены 33 Python контрпримера и четыре группы actual JS handler tests:
fallback даже на пустом ответе, неправильные echo/types, ночь через UTC
границу, включительный date range, весенний gap и осенний fold, ложный offset,
неверный timezone label, отсутствие network на invalid query, отказ до
archive/plan и сохранение всей cohort после ошибки истории.

Существующие искусственные provider fixtures теперь явно возвращают
запрошенные параметры и timezone. Они не выдаются за новые реальные матчи.
Полный release результат фиксируется в
`reports/FIXTURE_QUERY_CONTRACT_RELEASE_20261010.json`; final-head CI — в PR.

## Следующий шаг

Нужны подтверждённый provider timezone contract и новые полные FT history
packets плюс будущая prematch cohort. Старые снимки не стали новым HOLDOUT.
Сравнение Brier/log loss/EV/CLV по-прежнему невозможно на нулевой допущенной
выборке; программные тесты подтверждают обработку источника, не accuracy.

Описание timezone/fixture.timestamp у поставщика:
https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
Внешняя документация объясняет ожидаемый контракт, но не аттестует старые пакеты.
