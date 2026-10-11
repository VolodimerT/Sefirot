# SEFIROT Chat Standard V1 — 11.10.2026

Нормативный контракт первого P0 для Issue #33 и аудита V4.0. Версия JSON:
`sefirot-chat-answer-v1`. Канонические файлы: `schema/chat_answer_v1.json`,
`research/chat_answer_contract.py`, `scripts/verify_chat_answer.py`.
Исходный CORE и его money/policy/model modules не изменены.

## Граница первого PR

Это работающий **операторский read-only verifier**, а не подключённый ко всем
чатам сервис. JSON Schema проверяет структуру; Python дополнительно проверяет
семантику и оригинальную запись. Промпт, самостоятельно заявленный hash и
наличие кода в GitHub не доказывают исполнения. Не показывать непроверенный
JSON как машинно подтверждённый результат.

В первой версии проверены оригинальный архивный CORE либо его отсутствие,
конфликты времени/fixture/live и sanity counts small markets. Current-phase,
bookmaker-price и settlement attestation adapters ещё не подключены.
Поэтому текущая фаза HOLD, цен 0, альтернатив 0 и `monetary_permission=false`.
В полном V4 следующие отдельные PR подключают качество истории, shadow models,
цены и калибровку. Этот PR не закрывает Issue #33 целиком.

## Пять разных категорий доказательств

| Категория | Что доказывает | Ограничение первого P0 |
|---|---|---|
| CORE_BET | Сохранённый оригинальный BET | Только факт архивного решения, не текущий допуск |
| CORE_PASS | Сохранённый оригинальный PASS | Не заменяется исследовательским BET |
| RESEARCH_ONLY | Исследовательская гипотеза/отсутствие исполнения | Нет P/EV и денежного допуска в этом ответе |
| BOOKMAKER_QUOTE_OBSERVED | Подтверждённая точная цена | Adapter отсутствует: такое утверждение отклоняется |
| REAL_TICKET_SETTLED | Подтверждённый расчёт реального купона | Adapter отсутствует: такое утверждение отклоняется |

`OUR_PARIK24_TICKET` — **source class**, а не синоним REAL_TICKET_SETTLED.
OPEN/PENDING/CASHOUT/user-reported WON не подтверждают settlement. Допустимый
`ticket_record` явно `USER_REPORTED_NOT_ATTESTED`; он не создаёт финансовую
запись. `EXTERNAL_STAKE_YARYI_PROPOSAL` нельзя выдавать за наш Parik24-купон.
Дальнейший журнал должен хранить отдельно SEFIROT_CORE_DECISION,
SEFIROT_RESEARCH_CANDIDATE, EXTERNAL_STAKE_YARYI_PROPOSAL и OUR_PARIK24_TICKET.

## Обязательные поля и источник доверия

Все поля схемы обязательны; отсутствующее доказательство — явный null,
а не выдуманный ID. Unknown fields, NaN/Infinity, duplicate JSON keys,
неизвестные enum и денежный допуск true отклоняются.

- `fixture_id`, `requested_scope`: только исходные матчи. Оператор отдельно
  передаёт исходный scope; значение из ответа не считается этим scope.
- `mode`, `phase_source`: PREMATCH возможен только при операторском archive
  и оригинальном prematch seal. Для неподтверждённой текущей фазы — HOLD.
  LIVE_RESEARCH/POSTMATCH зарезервированы для будущего attested adapter;
  нельзя включить их собственным JSON.
- `observed_at`, `received_at`, `answered_at`: aware RFC3339, source <= receipt
  <= answer <= operator clock. Текущий ответ старше 120 секунд отклоняется.
- `runtime_status`, `model_build`, `model_hash`, `code_hash`, `policy_hash`,
  `forecast_seal_id`, `decision_id`, `core_decision`, `core_class`: связываются
  с записью из одобренного оператором оригинального read-only ledger.
  Проверяется весь hash journal и digest prediction/decision, а не клиентский
  hash. Архивное исполнение не называется новым запуском.
- `data_origin`: SYNTHETIC явно виден; запись в durable ledger сама по себе
  не удостоверяет поставщика. Для несинтетической записи без внешнего
  origin attestation — ORIGIN_NOT_INDEPENDENTLY_ATTESTED.
- `evidence_level`, `source_conflicts`, `missing_data`: все исходные CORE
  limiting_factors сохраняются. Любой конфликт требует HOLD. Нет исходного
  решения — SEFIROT_NOT_EXECUTED / NO_MODEL_DECISION / RESEARCH_ONLY,
  а не сфабрикованный CORE_PASS.
- `priced_market_count=0`, `alternatives_ge_2=[]`: отсутствие валидной цены
  явно NO_VERIFIED_ALTERNATIVE. Зарезервированная форма альтернатив имеет
  включительный floor 2.00 и максимум 3 рынка того же scope, но **любая
  непустая альтернатива отклоняется**, пока независимый price adapter не
  подключён. Это не реализованный поиск букмекера.
- `next_action`: фиксированный список действий без свободного совета играть.
- `ticket_record`, `audit_period`, `monetary_permission`: отдельное
  непроверенное пользовательское сообщение, календарный день (для архива
  Europe/Kyiv), текущий денежный допуск всегда false.
- `live_state`, `research_checks`: непроверенные исходные утверждения для
  обнаружения противоречий, не source admission или прогноз.

Факт архивного BET/PASS не означает, что odds/receipt/status актуальны.
CLI принимает доверенный путь к **существующей** операторской копии ledger,
не скачивает БД, не удостоверяет произвольный файл как production-origin,
не запускает capture/decide и не пишет БД. Подлинность экспорта обязан
проверить оператор отдельно (в этой разработке — authenticated durable snapshot
+ checksum). Без этой границы исходный файл нельзя назвать оригинальным.
`--at` и `--archive` — операторские audit controls, не поля ответа модели.

## Короткий русский ответ

Renderer принимает только immutable результат `validate_answer`, не dict
пользователя. Семь строк; для LIVE восемь с дополнительным состоянием и
обоими временем наблюдения. Внешний чат должен публиковать этот renderer,
а не добавлять собственное «заходим» после PASS.

```text
Матч: [команды, турнир, kickoff] | Режим: HOLD
Источник: [оригинальная архивная запись или НЕ ЗАПУЩЕН]; время ответа
SEFIROT: PASS/НЕ ПОЛУЧЕН | класс | текущий денежный допуск: false
Точная линия: НЕ ПОДТВЕРЖДЕНА
Альтернативы >=2.00: НЕТ — NO_VERIFIED_ALTERNATIVE
Блокеры: [три приоритетных; полный список в JSON]
Следующий шаг: [одно безопасное действие]
```

При LIVE конфликте 0:0 против котировки 1:0 требуется LIVE_STATE_CONFLICT,
для устаревшего снимка >30 секунд — LIVE_DATA_STALE; всегда
LIVE_MODEL_UNVALIDATED и HOLD. Эти 30/120 секунд — инженерные лимиты первой
версии, не эмпирически доказанные пороги прибыльности. Атомарный source receipt
со всеми событиями/красными/quote revisions пока не реализован. Совпавшие
пользовательские scores не разрешают LIVE-прогноз.

## Small-market readiness preview

`research/small_market_readiness.py::preview` принимает exact metric/period
и восемь nullable counts. Missing != zero. SOT > SHOTS и corners_1H > FT
карантинируются. SHOTS, SOT, FOULS, YC, RC, booking points независимые units;
фолы не заполняют missing YC, goal lambda не принимается как corner input.
Карточки требуют отдельные referee и settlement blockers. FT не подставляется
в отсутствующий 1H/2H count. Все computed blockers должны присутствовать в
answer.missing_data; скрыть их нельзя.

Это **подготовка QC**, не полный `small-match-observation-v2`: пока нет
normalized IDs, receipt attestation, pagination/assigned fixture denominator,
competition exclusions/revision history и проверенного settlement/referee.
Заявление `full_league_verified=true` отклоняется. Даже все заполненные counts
не дают GREEN: fit_allowed=false, probability=null, ev=null. Следующий P0 PR
реализует full-league QC с независимым знаменателем и quarantine manifests.

## Запуск и воспроизведение

Из корня репозитория:

```sh
python scripts/verify_chat_answer.py --answer examples/chat_answer_not_executed_v1.json --fixture demo:contract:unknown --at 2026-10-11T17:00:00Z
python -m unittest discover -s tests -p test_chat_answer_contract.py
python test_sefirot.py
python scripts/verify_release.py
```

Первый пример намеренно fixed-time NO_MODEL_DECISION, а не реальный матч.
В текущем использовании builder ставит фактическое время; не копировать
пример как текущий ответ. Для оригинального решения оператор передаёт
`--db /path/to/approved-original.sqlite`; исходный JSON можно собрать через
`build_answer(..., repo=readonly_repo, decision_id=original_id)`. Для исторической
PREMATCH-проверки добавить `archive=True` в builder и `--archive` в CLI.
CLI возвращает UTF-8 JSON, exit 0 valid / exit 2 rejected. Не помещать личные
SQLite, купоны, receipts и токены в публичный Git.

Tests включают подмену PASS/raw EV/class/hashes, испорченный ledger, отсутствие
runtime, duplicate keys, исходный scope, source clocks, LIVE конфликт, cashout,
малые counts и попытки придуманной цены. Три текстовых запроса проверяют
идентичность детерминированного JSON pipeline; это **не тест трёх настоящих
независимых GPT-чатов** и не доказательство prompt compliance.

## Применение ко всем чатам проекта

Готовый текст: `docs/SEFIROT_CHAT_PROJECT_INSTRUCTIONS_V1_20261011.md`.
Его надо явно вставить в Instructions нужного ChatGPT Project и подключить
операторский вызов verifier. Настройки Project этим PR не прочитаны и не
изменены; автоматическое применение ко всем чатам не утверждается.
После подключения вручную сравнить три независимых чата на одинаковых fixtures
и original IDs: «на матч», «как Ярый», «коэффициент 2.5», «LIVE 1:0», «я сыграл»,
«новый чат», «другой букмекер», «модель PASS». Все должны сохранять original
verdict, provenance, scope, явный 0 альтернатив и не допускать денежный grant.

Внутридневный финансовый append-only журнал и единый финальный аудит дня —
следующая интеграция, здесь не создан скрытый банк/автоматизация/новый ticket
ledger. Существующий CORE journal только читается. Не объявлять этот пункт
выполненным по одному полю ticket_record. Остановиться после первого рабочего
P0 PR и отчёта; следующий инженерный этап — отдельный full-league QC PR.
