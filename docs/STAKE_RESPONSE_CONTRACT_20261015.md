# Stake: неоднозначный JSON и повреждённый каталог

Исходный кандидат: `c4d9e4d9703a891ed0c9cd45948c336e2c14ddac`.
Этот этап исправляет только существующий экспериментальный адаптер;
официальный Sports Data API и очередь stake_snapshot не включаются.

## Подтверждённые ошибки

- HTTP 200 с fixture.data в виде списка/строки вызывал AttributeError вместо
  фиксированного отказа. api-health не перехватывал это исключение; CLI падал
  без нормального диагностического отчёта.
- Повторяющиеся JSON keys, включая data и эквивалентный escaped key, незаметно
  заменяли прежнее значение. Квитанция хэшировала уже неоднозначно разобранный
  объект. Это не доказательство подлинности сырых байтов ответа.
- Повреждённые элементы tournament/fixture пропускались; false вместо списка
  превращалось в пустой список. В результате повреждённый ответ мог выглядеть
  как успешный пустой каталог.
- NaN/Infinity и переполнение 1e999 давали несогласованный ValueError при hash;
  отдельного ограничителя вложенности JSON не было.

## Изменение

До создания receipt payload проходит один строгий JSON parser: запрещены
повторные decoded keys, NaN/Infinity и не конечные float после переполнения.
Максимум 64 уровня контейнеров, считая корневой; malformed encoding/JSON,
превышение depth и ошибка рекурсии дают StakeRequestError(INVALID_JSON).
Итеративный обход использует память по глубине, не дополнительный список
всех элементов широкого массива. Фигурные скобки внутри строк не считаются
структурой. Легитимный payload и его прежний canonical hash сохраняются.

Каталог проверяет типы tournament/fixture/data и списков fixtureList/competitors.
Некорректные типы дают INVALID_RESPONSE; nullable data и outright без двух
competitors не превращаются в match fixtures. Семантика неизвестных статусов,
рынков и официального API не предполагается и не добавляется.

В обоих случаях api-health возвращает REQUEST_FAILED с фиксированным reason,
CLI exit 2, без traceback или произвольного upstream текста. Ответ закрывается,
повторов запроса нет. Query/auth/redirect/TLS, лимиты событий и байтов неизменны.
Market access остаётся NOT_CHECKED, денежный допуск false.

## Проверки и границы

Восемь новых тестов используют реальный loopback HTTP и стандартные
HTTPResponse/JSON parser. На исходном коде — 9 failures/10 errors с subtests;
после исправления профиль Stake 43/43 и API health 19/19.
Проверяются duplicate/escaped keys, NaN/Infinity/overflow, depth 64/65/1200,
строковые скобки, malformed/nullable/ordinary fixtures, закрытие response,
один запрос и CLI diagnostic без credential/account sentinel.

Токен в тестах синтетический; production env/vault не читаются. Реальных
запросов к Stake/другим провайдерам — 0. Оригинальные packets/seals/receipts,
Policy/MODEL_MODULES и протокол не меняются. code_hash меняется из-за одного
не модельного src файла; model_hash прежний. Старые записи не пересчитываются.

Официальный доступ Stake/OpenAPI/terms и настоящая разрешённая котировка
остаются NOT_VERIFIED. stake_snapshot остаётся запрещённым в SAFE_KINDS.
Deployment/hosted SQL/main merge/API budget, реальные fit/HOLDOUT и ставки
не выполняются. RESEARCH_ONLY / PASS / stake=0.

Точный опубликованный SHA, isolated full release и CI push+PR фиксируются
в итоговом отчёте этапа. Зелёный CI не подтверждает доступ к внешнему API.
