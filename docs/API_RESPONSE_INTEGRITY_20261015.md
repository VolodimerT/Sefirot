# API: целостность HTTP-ответа и безопасный отказ

База unified draft PR #56: `df0f6f6ad8d9673be480e373e63772660f7137fd`.

Подтверждены две ошибки высокого приоритета (P1):

- Оборванный chunked-ответ и некорректная HTTP status line обходили обработку
  ошибок в общих клиентах API-Football/Odds catalogue, Stake и клиенте шлюза.
  `IncompleteRead`/`BadStatusLine` уходили вызывающему коду; api-health мог
  завершиться исключением. Текст некорректной status line попадал в исключение.
  Тесты используют только собственный маркер; реальная утечка ключа не заявляется.
- При read(limit) стандартный HTTP parser мог вернуть корректный JSON-фрагмент,
  хотя тело было короче заявленного Content-Length. Такой фрагмент принимался
  за полный ответ и получал успешную receipt. Также принимались ошибочные или
  конфликтующие Content-Length и Transfer-Encoding + Content-Length.

Дополнительно исправлена ошибка P2: OSError при close мог заменить основной
отказ и передать наружу произвольный текст исключения. Cleanup теперь сохраняет
первичный результат, не выводит сетевые ошибки закрытия и не повторяет запрос.

Все пять путей используют один read_response: API-Football, Odds catalogue,
Odds events, Stake GraphQL, sports gateway. Предел размера ответа сохранён.
Проверяются числовая длина и её совпадение с фактически прочитанным телом;
неоднозначный framing отклоняется. HTTPException превращается в прежний
фиксированный отказ провайдера, у Stake — NETWORK_ERROR. Полные fixed-length,
chunked и HTTP close-delimited ответы остаются доступными. Автоматических
повторов, новых endpoint, ключей, квот или денежного допуска нет.

10 регрессионных методов проверяют настоящие HTTPResponse над искусственными
потоками байтов; сеть, API-провайдеры и реальные секреты не используются.
На базе до исправления: 20 assertion failures и 14 uncaught-error subtests.
После исправления — 69/69 профильных тестов; полный release и exact-head CI
фиксируются в отдельном отчёте этапа. api-health возвращает API_CHECK_FAILED
без admission/monetary/execution вместо падения на разрыве ответа.

Изменены только четыре транспортных src-модуля. Точный code_hash меняется,
MODEL_MODULES, Model hash и Policy прежние. Старые исходные seals/decisions,
receipt, calibrator/approval, протокол и отчёты не переподписываются.

- code_hash: `aa21ded2003b575b35ef819e4cc388882409e7b3235cf06b27ddaf5863d0c89e`.
- model_hash: `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`.
- policy_hash: `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`.

Это исправление кода, не восстановление подписки API-Football и не подтверждение
реального доступа к Stake или действующей квоты. На текущем этапе не выполнялись
provider calls, collection, real fit, production writes, secret reads/changes,
main merge и deployment. Render по решению владельца отложен. Настоящие источники,
лицензия/квота, CAL/новый HOLDOUT и преимущество модели не подтверждены: PASS/0.
