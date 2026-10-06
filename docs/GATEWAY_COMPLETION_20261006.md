# Шлюз API-Football: завершение технического шага 06.10.2026

В feature/stability-reset-20261005 закрыт разрыв между существующим
облачным шлюзом, API-health и ограниченным сбором data-session.
Наличие server key теперь проверено реальным запросом; источник отклонил
доступ. Это завершённое техническое исправление, не готовая модель 2.5,
не успешная сборка спортивной выборки и не разрешение на ставки.

## Обработчик и клиент

`server/sports_gateway.js` — канонический самостоятельный Deno handler,
без сторонних зависимостей. Node contract suite исполняет именно его
через VM с подменённым transport, а не копию алгоритма. По умолчанию
DEPLOYED_AUTH пуст: обработчик отказывает всем credential. Deployment
приватно вставляет SHA-256 hashes runner credentials в отмеченную строку;
сами значения и compiled auth config не публикуются. Custom header auth
сохраняет прежний credential. Временный credential для этой проверки
отозван после запросов; повторная попытка получила HTTP 401 до upstream.

Provider key читается только сервером через существующий service-role RPC
из Vault. RPC input/response ограничены 16 KB, timeout 3 seconds;
provider response 2 MB/9 seconds. Redirects запрещены в обоих transports.
Endpoint/parameter whitelist соответствует sports provider; odds endpoint
не добавлен. Host фиксирован. Fixture response требует точного results
count, первой и полной страницы; неполные данные не получают receipt.
Status удаляет account fields, сохраняя subscription/requests. Numeric
quota headers проходят whitelist и передаются в клиентский receipt.
Они могут уменьшать бюджет, но не резервируют общую серверную квоту.

HTTP status upstream сохраняется как фиксированное число, включая outer
502. HTTP 200 с provider errors не становится успехом. Season/quota/auth/
access имеют отдельные причины; unknown messages не копируются.
Diagnostics содержат только известные имена полей и boolean mentions,
не account, токен или raw error. Сбор останавливает последующие запросы
при access/auth/quota/network failure, сохраняя объявленный знаменатель.

Прежний debug endpoint заменён на `server/retired_debug.js`: HTTP 410,
без чтения Vault или вызова provider. Schema/RPC/Vault key/подписка и
Render services не менялись. Проверка Supabase security advisors не
нашла lints. Неавторизованный основной endpoint получил HTTP 401.

## Реальная проверка и ограничения

До запроса объявлены те же семь league/profile IDs прежнего research
cohort: 5/MEN, 104/LOWER, 128/MEN, 141/MEN, 239/MEN, 334/LOWER, 506/LOWER.
Дата Europe/Kyiv 06.10.2026; source reliability 0.8 — утверждение оператора,
не сертификация API. Бюджет 12 попыток, reserve 5, grids выключены,
цены не запрашиваются. Это CALIBRATION research, не challenger HOLDOUT.
Исходный manifest и неуспешные попытки сохранены отдельно; просмотр
результатов не менял состав лиг или модель.

| Проверка | Фактический результат |
|---|---|
| final data-session, 15:31:19–15:31:34 UTC | COLLECTION_INCOMPLETE / PROVIDER_ACCESS_DENIED |
| transport attempts внутри этой сессии | 1, только status |
| пакеты / назначенные fixtures / прогнозы | 0 / 0 / 0 |
| api-health, отдельно 15:31 UTC | request_attempted=true, PROVIDER_ACCESS_DENIED |
| provider HTTP 200 | errors.access, поэтому не успешные данные |
| локальные Stake/Odds credentials | missing; sporting calls не выполнялись |
| execution / monetary permission / HOLDOUT | false / false / не пройден |

Предыдущая диагностика поля `access` не обнаружила mentions IP restriction,
credential, quota, subscription или inactivity. Эти false не исключают
перечисленные причины и не устанавливают настоящую причину в аккаунте.
Ранние и финальные status probes — отдельные обращения, не пять матчей
и не пять независимых наблюдений. За эту работу выполнено пять status
обращений к API-Football, ноль запросов fixtures/history/odds.
Старая запись Stake HTTP 403 за 05.10 остаётся исторической.

Восстановление доступа требует исправления account/key permissions на
стороне API-Football. Серверный ключ не извлекался; другой сезон или
ручные коэффициенты вместо отсутствующих данных не подставлялись.
После восстановления: api-health → новая заранее объявленная bounded
data-session → prematch seals → API settlement → полный forward-scorecard.
Для новой модели нужны будущие независимые наблюдения и отдельный
заранее замороженный протокол. Технический release этого не доказывает.

## Воспроизводимость

Локально Python 3.12/Linux: **517/517** tests, full release,
demo/replay/integrity успешны. Новые семь Python tests относительно 510
включают один aggregate из **18** Node handler contract groups:
auth/expiry, unsupported requests, byte/stream limits, redirect/timeout,
RPC config, error sanitization, account redaction, quota/count/pagination.
CI явно устанавливает Node 22 на Windows/Ubuntu × Python 3.11/3.13;
удалённый результат сверять на exact опубликованном head.

Семь MODEL_MODULES побайтно прежние относительно 8e6a3ab;
BASELINE_V1/Policy/caps не менялись. Historical seals не переподписывать.

- client code_hash: `2dbef0ef9819a3a724e0fae241211f862e735e84fe79a62a700e6e5072d9da57`;
- model_hash: `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`;
- server template SHA-256: `abfaaf4a6a143f9da73b9faafe18b612c4315256632f68ad914115ed04941e76`.

Client code_hash не включает серверный JavaScript. Deployment source
побайтно сверён с шаблоном после единственной auth-line substitution;
серверная identity указана отдельно. Private manifests/receipts и
финансовые аудиты в публичный Git не помещены. PR #11 сохраняет прежнюю
base feature/api-data-session-20261005; main merge не выполнялся.
