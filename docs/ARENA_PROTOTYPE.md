# SEFIROT ARENA v0: самостоятельная исследовательская надстройка

**Статус:** SHADOW ONLY, прогнозы и Policy не изменяются, stake=0. Это не 8 независимых прогнозных моделей, не доказательство прибыльности, не торговый робот. Новых спортивных/odds API-запросов нет. Зафиксированные основным ядром прогнозы не изменяются.

## Что делает

1. Принимает **исходный sealed prediction JSON** (`Service.capture`), целый объект с `id`, а не вручную набранные проценты, и необязательный список уже полученных котировок.
2. Проверяет точный hash прогноза, `captured_prematch`, отсутствие reconstructed, chronology (sports → seal → quote → now → kickoff), `Policy` identity, оригинальные 1–7 контрактов и 90-минутные правила.
3. Пропускает пять price-blind специалистов: **history**, **tactics**, **lineups**, **schedule**, **probability_critic**. Им не передаются котировки, EV, implied или итог чужого агента.
4. После price-blind фазы три специалиста: **market_auditor**, **risk_correlation**, **death_test**. Все восемь получают независимые запросы и не голосуют за денежный допуск.
5. Проверяемая программой арифметика: implied `1/odds`, effective fair odds при PUSH `(1-P(push))/P(win)`, `EV=(odds-1)*P(win)-P(loss)`, худшая граница по low и worst stress. Перечень `blockers` раскрывается для каждого рынка. Выбор `top_ev_market_diagnostic_only` **не является рекомендацией**.
6. Всегда выдаёт **ПРОПУСК**, `monetary_permission=false`, `stake=0`, `execution_enabled=false`. Никаких LIVE, догонов, API-заявок, эксперсс-пар или изменений БД.

## Запуск без ключа и оплаты

Запускать из корня репозитория (при установке `pip install -e .`):

```bash
python scripts/arena_shadow.py --demo --output arena_demo.json
```

Вместо демо можно анализировать заранее сохранённый seal (JSON из действительного `capture`), необязательные свежие цены и точный UTC timestamp до kickoff:

```bash
python scripts/arena_shadow.py --prediction prediction.json --quotes quotes.json --at 2026-10-08T12:00:00+03:00 --output arena_report.json
```

`--at` здесь **пример формата**, подставьте реальный момент после seal и до kickoff, относящийся к вашим данным. Пустая цена — допустима; тогда EV=null и допуск невозможен. Output только новый файл, overwrite запрещён.

`--mode offline` (default) — **8 детерминированных, ограниченных проверок, не GPT-агенты**. Демонстрация схемы и guards не валидирует тактику, lineup, вероятность или сильную модель.

## Опционально: GPT через Responses API

Только если сознательно нужен оплачиваемый внешний вызов (8 запросов, без API-сбора букмекера):

```bash
# OPENAI_API_KEY настройте приватно как переменную окружения ОС
python scripts/arena_shadow.py --demo --mode openai --model gpt-5-mini --output arena_gpt_demo.json
```

Данные fixture отправляются API OpenAI, токен не сохраняется в отчёте или репозитории. `store=false`, structured JSON, ссылки на evidence ID обязаны существовать. `UNKNOWN` разрешён; придуманные evidence IDs блокируются. **Никакого полного агентного браузера или автономного сбора фактов**. Экранные роли не являются восемью разными обученными моделями; используется восемь отдельных вызовов с различными задачами и изолированными контекстами.

## Что ещё нужно для реального применения

- Интеграция с локальной `work`-очередью исключительно через явный экспорт sealed JSON, не через перезапись ledger.
- Прямое использование готового `recheck`, confidence/holdout proof и полномочий основного `Service.decide` отдельно от ARENA; арена не имеет права проводить денежный допуск.
- Подтверждённый API-источник и forward-выборка, затем независимая проверка EV/CLV/holdout; пока API-Football приостановлен и прогнозная модель не прошла полноценный holdout.
- Роли `schedule`/`risk_correlation` не означают, что у текущего fixture есть подтверждённая свежая информация о графике или портфеле: при отсутствии данных статус UNKNOWN/CAUTION.

Запускаемые тесты: `python -m unittest discover -s tests -p test_arena.py -v`; внешний API в тестах только мокается. Файл находится **вне** `src/sefirot`, поэтому прежний code_hash и все MODEL_MODULES/Policy/CLI не меняются; основной PR #11 и работающий офлайн-процесс не затрагиваются. Любой новый `code_hash` для исходных файлов проверять по existing identity release gate.