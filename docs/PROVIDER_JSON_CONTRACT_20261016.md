# Целостность JSON на границе API, 16.10.2026

База: aa8b23b7695609b01f8c180bebbaa0c81847782e, существующий draft #56.

Подтверждено собственным локальным HTTP-сервером: повторяющиеся поля
(включая escaped aliases) незаметно заменяются при стандартном json.loads.
Общий transport API-Football/Odds мог выдать receipt для изменённой структуры.
Прямой Odds принимал NaN/Infinity/1e999. Слишком большой integer вызывал
ValueError с текстом декодера вместо установленной безопасной ошибки.
Глубина ответа не ограничивалась до проверки формы/создания хеша. Это ошибки
клиентского разбора; они не доказывают такие ответы настоящего поставщика.

Проверенный строгий parser Stake перенесён в provider_transport и используется
общим request_json, прямым Odds, Python-клиентом sports gateway и Stake.
Он отклоняет повторяющиеся decoded keys, nonfinite constants/float overflow и
JSON container depth >64. Обход дерева итеративный, память обхода зависит от
глубины. Это предел принятой структуры после стандартного разбора; ограничения
байтов и обработка RecursionError остаются дополнительными границами.
Валидные конечные числа, nullable fields и строковые скобки не меняются.
Обычные data и canonical payload_hash совпадают с прежними.

Сохраняются публичные ошибки: provider returned invalid JSON;
odds provider returned invalid JSON; PASS; sports gateway returned invalid JSON;
StakeRequestError INVALID_JSON. Не включаются исходный ответ, URL или ключ.
Один запрос, закрытие ответа, без retry. Auth/hosts/query, TLS, redirects,
HTTP framing/byte limits, quota/budget, PREMATCH и денежные gates не меняются.

Семь новых тестов используют ThreadingHTTPServer на 127.0.0.1, настоящие
HTTPConnection/HTTPResponse и только синтетические значения. Проверяются пять
путей: Football, Odds catalogue/events, gateway и Stake; duplicate/escaped keys,
NaN/Infinity/overflow, depth65/1200, invalid UTF-8/syntax/5000-digit integer,
valid payload hashes, depth64 gateway и скобки внутри строк. Сохранены восемь
ранее добавленных Stake regressions. Первый тестовый adapter неправильно
закрывал retained HTTPResponse; стенд исправлен, окончательный red повторён
на исходном tracked-file дереве. Полные red/green и CI сохраняются в отчёте.

Изменяются только четыре transport src, новый test, AGENTS и этот документ.
MODEL_MODULES/Policy, SQL/relay/worker, protocol и originals неизменны.
Новый code_hash не применяется к старым seals/fits/approvals автоматически.

Supabase changelog прочитан 16.10; предстоящее ограничение старых TLS1.2
ciphers не относится к JSON и не требует ослабления TLS. Invoke docs HTTP403;
обход доступа не выполнялся. Платформенные функции/схема не менялись.

Полный local release выполняется в отдельной копии; точный опубликованный
SHA проверяется всей матрицей push+PR. CI не подтверждает настоящую доступность
поставщиков или модельное преимущество. Hosted SQL rollout, official Stake
access, реальная цепочка источников и независимый HOLDOUT остаются блокерами.
RESEARCH_ONLY / PASS / stake=0. Без main merge, production и платных API.
