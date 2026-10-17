# Явное подтверждение правил и PREMATCH для The Odds API

Продолжение разрешённого offline пути после ответа поддержки Stake. База:
`701bb943e5a1ef53e147892fb30cc789b9a4b22b`, существующий draft #56.
Новый провайдер/вторая модель/ручной источник не добавляются.

## Подтверждённый дефект

`quotes_from_event` использовал truthiness: строка `"false"`, integer 1,
непустой список или объект принимались за согласие с settlement. Receipt затем
писал `rules_verified_by_operator=true`, хотя исходного boolean true не было.
Обе ветви импорта — только h2h и expanded main markets — были затронуты.

`require_prematch_seal` также принимал captured_prematch="false"/1 и
reconstructed=0/null либо отсутствие reconstructed. Это структурная ошибка
публичного адаптера. Она не доказывает обход полной ledger integrity или
денежного admission: CLI проверяет журнал и исходную build identity отдельно.

Теперь settlement требует `rules_confirmed is True`; prospective seal требует
`captured_prematch is True` и `reconstructed is False`. Unknown/missing и
неверные типы отвергаются исходными фиксированными ValueError, до чтения event
и price. Значения не преобразуются, receipt не создаётся, оригиналы не меняются.

## Проверки

Семь regressions с subtests: boolean/type matrix обеих ветвей импорта,
require_prematch_seal/event_candidates/quotes_from_event, missing flags,
валидные h2h и expanded lines, реальный CLI на owned synthetic SQLite.
Для проверки последней границы тест подменяет только результат Repository.get
в памяти после настоящей проверки исходного журнала; сохранённые записи не
портятся. Проверяются exit2, ноль catalogue/price/credential calls, отсутствие
quotes/receipt, исходные bytes принадлежащего тесту ledger.

Первый green выявил ещё одну подтверждённую ошибку: odds-events/fetch-odds
попадали в writable Repository bootstrap, меняли SQLite header даже при отказе
и создавали отсутствующий ledger. Две команды теперь используют существующий
read_only dispatch: чтение исходных prediction/verify не пишет данные, output
котировок остаётся отдельным файлом. Добавлена проверка missing parent/DB,
ноль requests и файлов. Исходный byte-equality assert сохранён, не ослаблен.

```sh
python -m unittest discover -s tests -p test_odds_confirmation_contract.py -v
python -m unittest discover -s tests -p test_odds_provider.py -v
python -m unittest discover -s tests -p test_market_expansion.py -v
python scripts/verify_release.py
```

Полный release выполняется в отдельной копии tracked tree. Точный опубликованный
commit, red/green, число тестов и полный OS/Python/native PostgreSQL CI
фиксируются в итоговом stage report и существующем draft PR #56.

## Что остаётся неподтверждённым

Это только строгость типов уже существующих подтверждений. Boolean true от
оператора не доказывает происхождение ответа, правила букмекера или право на
ставку. Receipt остаётся `THE_ODDS_API_V4`, available_at_bookmaker=UNVERIFIED;
такой источник нельзя переименовать в официальный Stake API.
Форма валидных quotes и их hashes остаётся прежней.

По присланному владельцем скриншоту поддержка Stake отказала в документации и
помощи по account API. Это не спецификация Sports Data API и не подтверждение
разрешённого odds access. Значение опубликованного account token не читалось
инструментами, не копировалось и не использовалось; подтверждения его отзыва нет.
Официальный адаптер без OpenAPI/условий/разрешённых samples не выдумывается.

Два non-model src меняют code_hash. MODEL_MODULES/Policy, остальные src,
SQL/worker/relay, frozen calibration protocol, старые seals/receipts и исходные
архивы сохраняются. Новых provider/платных запросов, credentials lookup,
hosted операций, deploy/main merge, budget activation, real fit/HOLDOUT и
денежных разрешений нет. **RESEARCH_ONLY / PASS / stake=0.**
