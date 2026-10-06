# Явная диагностика API, 06.10.2026

Наличие токена не подтверждает доступ к спортивным данным. `api-health`
теперь проверяет API-Football status и каталог одного выбранного odds
provider. Режим по умолчанию сохранён — The Odds API:

```powershell
py -3 sefirot.py api-health
py -3 sefirot.py api-health --odds-provider stake --output stake-health.json
```

Ключи читаются прежним credentials reader из environment/приватного
env-файла. Значения ключей не передаются в CLI arguments и не записываются
в отчёт. Спортивный status использует текущий direct/gateway transport.
Отчёт создаётся без БД, файл `--output` не перезаписывается.

## Что именно проверяется

Stake выполняет один `SportTournamentFixtureList`, `sport=soccer`,
`type=upcoming`, возвращает до пяти событий. Существующий provider helper
запрашивает до 10 tournaments × 10 fixtures; лимит ответа — 8 MB,
timeout — 20 seconds, redirects запрещены. Другие страницы не читаются,
повторных запросов нет. Отчёт содержит счётчик и credential-free receipt,
без списка событий. Пустой корректный каталог подтверждает выполнение
запроса, но не наличие подходящих матчей или полноценное покрытие.

UserIdentity, fixture groups, рынки и коэффициенты не запрашиваются.
`market_access=NOT_CHECKED`, `settlement=UNVERIFIED`,
`freshness=RECEIPT_TIME_ONLY`. Это диагностическая проверка каталога;
exact fixture/market mapping, спортивные premises и доступ к сезону
проверяются отдельно в collection/snapshot workflow.

Прежний `SEFIROT_STAKE_BOOT_PROBE` удалён: импорт модуля не запускает
запросы, даже при оставшемся environment flag. Прежний debug flag также
не разрешает вывод сырых provider errors. StakeRequestError сохраняет
совместимость с ValueError и отдаёт фиксированный code/HTTP status;
upstream bodies, сообщения GraphQL, account IDs и balance не выводятся.

| Результат | Значение |
|---|---|
| CREDENTIAL_UNAVAILABLE | Ключ отсутствует/невалиден; request_attempted=false |
| REQUEST_FAILED + HTTP_AUTH_REJECTED / 401 | Запрос отклонён по аутентификации |
| REQUEST_FAILED + HTTP_ACCESS_DENIED / 403 | Доступ отклонён; это не доказательство отсутствия токена |
| REQUEST_FAILED + HTTP_RATE_LIMITED / 429 | HTTP rate limit |
| REQUEST_FAILED + PROVIDER_ACCESS_DENIED | API-Football errors.access даже при HTTP 200 |
| REQUEST_FAILED + NETWORK_ERROR | Ошибка транспорта без раскрытия URL/ключа |
| REQUEST_FAILED + GRAPHQL_ERROR | Ошибка GraphQL; сырые messages не сохраняются |
| API_READY | API-Football subscription active и каталог The Odds API прочитан |
| RESEARCH_API_READY | API-Football subscription active и каталог Stake прочитан |
| API_CHECK_FAILED | Хотя бы один выбранный provider не прошёл проверку |

FootballRequestError сохраняет фиксированные причины квоты/auth/сезона.
Неизвестные ошибки нормализуются без копирования exception text.
CLI exit code — 0 для API_READY/RESEARCH_API_READY, 2 при отказе.
Во всех случаях admission_ready=false, monetary_permission=false,
execution_enabled=false. Доступность каталога не подтверждает достаточную
квоту для сборки, доступ к истории, корректность рынков или денежный допуск.

## Проверка и фактический предел

19 новых offline тестов: token configured + HTTP 403, различение 401/429,
network/JSON/GraphQL/size errors, закрытие HTTP response, отсутствие частных
values при старом debug flag, cold import без сети, ровно один ограниченный
запрос без аккаунта/цен, default The Odds API, gateway вместо локального
sports key, missing credentials без I/O, CLI exit/output без БД.
Этот этап прошёл 510 тестов; после gateway follow-up полный локальный
release: **517/517**, demo/replay/integrity успешны.

Семь MODEL_MODULES побайтно прежние относительно 8e6a3ab; BASELINE_V1,
Policy и monetary caps не менялись. Новая code identity требует обычной
проверки совместимости seals; исторические записи не переподписывать.

Ранняя проверка локальной среды 06.10.2026 06:26 UTC: sports/Odds/Stake credentials
MISSING_OR_INVALID, оба выбранных provider checks не выполняли запросов.
Новый sporting dataset и реальные forecasts не получены. В ранее
полученном журнале облачного Stake probe за 05.10.2026 22:24 UTC:
аутентификация UserIdentity прошла, последующий sporting request — HTTP 403.
Позднейший token-configured health не проверял каталог. Исторический отказ
не утверждает текущее состояние API.

Поздняя проверка 06.10.2026 15:31 UTC использовала существующий sports
gateway и серверный key без его извлечения: `REQUEST_FAILED`,
`request_attempted=true`, `PROVIDER_ACCESS_DENIED`. Stake request не
выполнялся из-за отсутствия local credential. Шлюз обновлён; временный
runner credential после проверки отозван. Provider key/подписка не менялись.
Причина ошибки внутри аккаунта поставщика не установлена; наличие
`access` не доказывает истечение ключа, Free limit или блокировку IP.
См. [итог проверки шлюза](GATEWAY_COMPLETION_20261006.md).

Дальнейший сбор — явный запуск этой сборки в уже настроенной среде,
api-health → bounded data-session → prospective scorecard. Main merge,
LIVE, догон, автоставки и Tavily не включены. Forecast accuracy/profitability
этими программными тестами не доказаны.
