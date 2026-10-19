# Unicode и каталог api-health, 16.10.2026

База ca5b3f1274664772f21a67b327507857c810fbdb; существующий draft #56.

## Подтверждённые ошибки

JSON decoder Python принимает escaped lone surrogates, например \ud800 или
\udfff, в ключах и значениях. Canonical UTF-8 digest затем вызывает
UnicodeEncodeError. Прямой Odds events мог вернуть непереносимую структуру
дальнейшему потребителю без отказа. На этих bytes нельзя подтверждать receipt.
Это локальные контрпримеры; такие ответы настоящего поставщика не наблюдались.

api-health предполагает dict в каждой строке Odds sports directory и строку в
поле key. Null, string, bool, int, list или нестроковый key дают AttributeError,
который не обрабатывается как отказ API и уходит из CLI. Воспроизведены восемь
вариантов через собственный HTTP-сервер и настоящий JSON parser.

## Исправления

Общий строгий parser проверяет decoded object keys и string values на диапазон
surrogate U+D800–U+DFFF до возврата/receipt. Это фиксированная INVALID_JSON
ошибка соответствующего транспорта, без исходного ответа/токена. Корректные
Unicode scalars и escaped surrogate pairs допустимы. Нормализация, replacement
или пересчёт старых canonical hashes не применяются: NFC/NFD остаются разными,
валидный U+FFFD допустим. Модельный canonical/digest не меняется.

api-health явно проверяет типы потребляемых rows и key перед подсчётом. Он
отказывает целиком, не фильтрует плохие строки и не скрывает произвольные
AttributeError широким except. Сохраняются существующие ValueError diagnostics:
REQUEST_FAILED / NETWORK_OR_PROVIDER_RESPONSE, CLI exit2, JSON без traceback,
Repository не открывается. Empty list, неизвестные поля и missing key сохраняют
прежнюю совместимость: missing key считается отсутствием soccer prefix.
Новых требований к официальной схеме Odds не вводится.

## Проверка и границы

Шесть новых методов дополняют семь существующих owned-loopback HTTP tests.
Окончательный red на baseline: 35 subtest failures, 8 errors; green 13/13.
Покрыты пять путей (Football, Odds catalogue/events, gateway, Stake), ключи и
значения с lone surrogates, valid escaped/raw supplementary Unicode,
сохранность data/hash и отсутствие Unicode normalization. CLI tests проверяют
malformed/valid/empty Odds catalogue, одно обращение, закрытие ответа и
отсутствие приватного synthetic sentinel. Credential patch только синтетический.
Профили и isolated full release/полный exact-head push+PR CI фиксируются
в отдельном отчёте; синтетические тесты не доказывают доступность внешних API.

Меняются только provider_transport.py, api_health.py, существующий HTTP test,
AGENTS и этот документ. Остальные src/Policy/MODEL_MODULES, SQL/worker/relay,
protocol и originals побайтово сохраняются. Auth/hosts/query/TLS/redirects,
framing/byte/quota/budget, PREMATCH и денежные gates не меняются.

Официальный Stake access/contract/terms, настоящий разрешённый price receipt,
реальные PREMATCH источники, независимый HOLDOUT и model edge остаются
неподтверждёнными. Hosted rollout и main merge не выполняются.
RESEARCH_ONLY / PASS / stake=0. Нет новых provider/paid calls, budget activation,
secret reads/changes, production/deploy/restart, real fit или денежных ставок.
