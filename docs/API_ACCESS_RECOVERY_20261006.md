# API-Football: приостановка аккаунта и защита квоты

06.10.2026 16:18:54 UTC явный `api-health --odds-provider stake` выполнил
один status-запрос через существующий Supabase gateway. Поставщик сообщил
о приостановке аккаунта: `PROVIDER_ACCOUNT_SUSPENDED`. Утренние журналы
существующего Render runner за 06:25 и 08:02 UTC содержали то же сообщение.
Причина приостановки не установлена. Неверный key, тариф, дневной лимит или
IP block не выводятся из сообщения; восстановление требует действий
владельца в API-Football. Смена key, оплата и обход не выполнялись.

Vault key имеет ожидаемый формат. Существующий SECURITY DEFINER RPC
возвращает именно названную Vault запись; execute разрешён service_role,
запрещён anon/authenticated. Проверялись boolean/metadata, provider key
не извлекался. Формат не доказывает действительность ключа.

## Исправленное поведение

- HTTP 200 с `errors.rateLimit`, включая изменение регистра, становится
  `PROVIDER_QUOTA_EXHAUSTED`; collector прекращает остальные обращения.
- Явное `account … suspended` в `errors.access` получает отдельную причину.
  Отрицание и неизвестные сообщения остаются `PROVIDER_ACCESS_DENIED`.
  Raw значения не выходят в ошибки/diagnostics.
- Дневной `x-ratelimit-requests-remaining` и минутный `x-ratelimit-remaining`
  сохраняются отдельно. Допускается также `x-ratelimit-limit`. Значения —
  только ASCII decimal длиной 1–12; malformed/private значения отклоняются.
- Оба известных бюджета уменьшаются на попытку; header может только
  понизить остаток. Известный ноль минутного бюджета останавливает I/O с
  `PROVIDER_RATE_LIMIT_WINDOW_EXHAUSTED`. Неизвестный header остаётся
  неизвестным; сброс окна не предполагается. Auto retry и sleep отсутствуют.
- Ошибки/пропуски остаются в назначенном знаменателе, дневной reserve сохранён.

Это лимит одной сессии, не глобальная атомарная резервация. Параллельные
процессы и общий IP могут расходовать квоту независимо.

## Проверка

Полный локальный release: **527/527**, demo/replay/integrity успешны.
Десять новых Python контрпримеров относительно 517; существующий aggregate
исполняет **19** Node contract groups фактического handler. Проверены оба
транспорта, rateLimit, separate day/minute headers, malformed/private
значения, остановка до date/history, рост headers без пополнения,
сохранение cohort, suspension и отрицание.

Server v9 побайтно сверён после одной приватной подстановки auth-line.
Исходный credential сохранён, временный удалён: повторно HTTP 401, как и
без credential; старый debug HTTP 410. Предварительная v7 проверка получила
gateway 401 из-за неверного типа временного expiry и до API не дошла;
v8 использовала правильный numeric expiry. Этот 401 не provider observation.
За это продолжение — **один** API-Football status и ноль fixtures/history/odds.
Stake credential отсутствует, вызовов 0. Schema/Vault key/подписка/Render
services не менялись. Main merge не выполнен.

Семь MODEL_MODULES побайтно прежние относительно точной базы 8e6a3ab;
BASELINE_V1 и Policy сохранены. Historical seals не переподписаны.

| Identity | Значение |
|---|---|
| client code_hash | `01d895ab7e2a09143c0dc11262fa52313c98e88462301436e6014067221597c9` |
| model_hash | `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617` |
| policy_hash | `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9` |
| server template SHA-256 | `5f019b238bf8423879002f2040c617aef5fe4de3e86f9e5447e1795f7397b8f1` |

JS server не входит в client code_hash. Public template имеет пустую
DEPLOYED_AUTH и fail closed. CI проверяется на опубликованном exact head;
локальный отчёт не выдаётся за удалённый результат. Старые REPORT/manifests
с их identities сохранены, не переписаны под новый runtime.
После восстановления: api-health → новая заранее назначенная bounded
data-session → prematch seals → API settlement → forward-scorecard.
Новых sporting observations, цены, допуска или HOLDOUT эти проверки не дают.

Официальные технические справки:
[rateLimit и квота](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage),
[минутные и дневные headers](https://www.api-football.com/news/post/how-ratelimit-works).
