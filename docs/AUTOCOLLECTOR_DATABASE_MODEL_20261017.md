# API-Football → проверяемый источник → существующий SEFIROT

База: PR #56 `c558486a290362e0924fcbfdac2a51e47ae5df63`, его CI 20/20 success.
Это подготовка кандидата, не production rollout. Stake исключён из этого этапа.
Модельные модули и Policy не изменены; RESEARCH_ONLY / PASS / stake=0.

## Что было и что исправлено

Работали защищённый Gateway, shared budget, leased sports_probe worker,
оригинальные receipts в отдельных ответах очереди, Repository/Service,
sports_archive, small_source_adapter и calibration_fit_gate. Но это не была
автоматическая цепочка: отдельного постоянного source archive и активного
ежедневного планировщика в проверенной Supabase не было (pg_cron отсутствует).
Render содержит web service, не подтверждён постоянно активный background worker.

Подтверждённые дефекты и разрывы:

- Файловый sports_archive писал сразу в окончательный JSON. Ошибка записи могла
  оставить повреждённый файл. Теперь публикация атомарная и без перезаписи.
- Probe ограничивал любой fixtures response 100 строками: полное расписание
  лиги могло быть отклонено. До 10 000 строк разрешены только для точного
  league/season и при обязательном sink, вызываемом ДО compact mapper.
- Успех provider fetch и сбой worker/mapper/completion не гарантировали отдельного
  долговечного источника. Новый opt-in Gateway сначала сохраняет пакет SQL RPC,
  затем выдаёт receipt/хеш подтверждения. Intent до I/O запрещает повтор запроса.
- Старый enrichment executor допускал 8–10 запросов. Сейчас предел 5, включая
  status и базовые запросы; reserve>=5, pacing и shared limiter сохранены.
- Не было безопасного импорта существующих source packets в модельные входы:
  добавлен слой research, использующий исходный Repository, archive/export_sports
  и review_small_market, без второго прогнозного движка и без capture/decide.

Raw source сохраняется отдельной транзакцией до QC. Отказ/сбой нормализации
не удаляет источник; дедупликация по SHA256 исходных импортированных байтов.
QC и локальная доступность имеют свои времена/хеш адаптера. Нельзя задним числом
экспортировать знания, полученные/проверенные позже. Исторические прогнозы и
их журнал не открываются на запись. Повторный импорт после обновления адаптера
добавляет новый QC, не заменяя старый. Это не миграция старых seals на новую сборку.

Храним оригинальный сохранённый gateway/source_packet и его receipt; это
**не оригинальные HTTP wire bytes и не подпись провайдера**. Для старых packets
provider_origin_attested=false. Аккаунтные status-поля и ключи не сохраняются;
небезопасные/неизвестные значения отклоняются до хранилища. SQL/Gateway
нормализуют имена чувствительных полей так же, как Python, включая пробелы
и пунктуацию; отдельный synthetic red/green проверяет этот контрпример. Ошибки провайдера
остаются в существующих защищённых budget/queue receipts с безопасными кодами,
они не выдаются за успешные спортивные пакеты.

## Повторная проверка реальных источников

17.10.2026 18:04 UTC: 3 настоящих сохранённых packets, 4 будущих fixture IDs АПЛ
2026 из date-filtered ответа, 1 statistics packet без связанного FT fixture,
1 очищенный status packet. Полного календаря нет: expected_matches=null,
а не выдуманные 380. Связанных FT/пригодных исторических observations — 0.

Все 3 packets прошли импорт/QC; дубликатов источника при повторном импорте нет.
Для каждого из 4 матчей получен настоящий существующий main model input и
8 small-market diagnostics inputs. Истории 0, вероятности/EV=null, прогнозы,
cohort assignments и решения не создавались. Orphan statistics сохранены,
но не включены в расчёт. Это проверка настоящих **сохранённых** данных без новых
API-запросов; не end-to-end проверка нового облачного deployment.
Исходный SQLite revision59 сохранил SHA256
`3ae7ad31957eebba32ef9d337a07cc335f79c95144112fb2502df42a48581ba2`.

Голы/основные рынки готовы к исследовательскому импорту при появлении проверенной
FT-истории. Corners/shots/SOT/yellow cards — отдельные diagnostics в SHADOW;
пропуски остаются null, нули сохраняются. Fouls остаются SHADOW/NOT_VERIFIED:
семантика совершённых/полученных фолов не доказана.

## Использование без сетевых запросов

Хранить source.sqlite отдельно от original prediction ledger, вне Git и веб-корня.
Команды создают отчёт исключительно под новым именем (режим 0600).

```bash
python scripts/football_pipeline.py --source-db /private/source.sqlite --output /private/import.json import-probes /private/saved-probe-responses.json
python scripts/football_pipeline.py --source-db /private/source.sqlite --output /private/coverage.json coverage --league 39 --season 2026
python scripts/football_pipeline.py --source-db /private/source.sqlite --output /private/plan.json daily --league 39 --season 2026
python scripts/football_pipeline.py --source-db /private/source.sqlite --output /private/inputs.json inputs --fixture 1557427 --profile MEN --source-reliability 0.8
python scripts/football_pipeline.py --source-db /private/source.sqlite --output /private/calibration.json calibration --prediction-db /private/original.sqlite
```

profile/source-reliability — явные исследовательские утверждения оператора,
не автоматическая сертификация источника. `calibration` вызывает существующий
fit gate только для чтения; он не делает fit/резервирование выборок.
`sync-archive` после согласованного rollout читает private relay source_export,
сверяет оригинальные байты/хеш и использует тот же импорт. Вызовов provider=0.
Каждая синхронизация перечитывает порядок хешей сначала, чтобы поздний INSERT
с меньшим хешем не терялся навсегда. При лимите страниц продолжение — новый scan.

`daily` без флага — только план. `--execute-permitted-window` отдельно разрешает
локальный существующий guarded collector с committed intents и persistence sink;
это не планировщик и не разрешение на квоту. На непостоянном Render-диске этот
локальный режим НЕ использовать: production путь — SQL queue/Gateway archive.
Для любой реальной отправки требуется отдельное разрешение владельца и штатное
действующее окно бюджета. Ни один путь его не включает и не пополняет.

## Ежедневное накопление и ограничения

Подготовленный SQL planner owner-only, по умолчанию не имеет расписания и
не доступен service_role. Один полный league/season calendar обновляет также
подтверждённые FT результаты. Затем — недостающая статистика до общего предела
5 запросов за UTC-сутки, не 5 на каждую лигу. Календарь и статистика дедуплицируются;
неопределённый dispatch не повторяется автоматически даже на следующий день.
Следующие лиги задаются параметрами той же функции. Отчёт отличает неизвестный
размер календаря, принятые/отклонённые матчи, неподвязанные statistics, конфликты
идентичности/результата, недостающие показатели и QC backlog.

Новый Gateway source_begin сериализует intent, проверяет RUNNING/attempt1,
точный endpoint/params/job, общие 5 dispatches/provider attempts в сутки и
не допускает повтор того же job/query. За provider reservation, минутный интервал,
reserve5 и паузу при неопределённом результате отвечает прежний shared limiter.
Worker opt-in дополнительно проверяет archive readiness ДО claim и ждёт 61 секунду
между sports jobs. При первом сбое нет автоматического provider retry.

Полной предматчевой истории из одного date packet не получить. При ограничении
5/day накопление займёт время. До реальной полноты не обещаем рабочие P/EV.
Наличие pg_cron/другого оплаченного scheduler и постоянно работающего consumer
нужно отдельно согласовать; новый платный Render-сервис не создан.

## Ручная цена и калибровка

```bash
python scripts/operator_cockpit.py --db /private/original.sqlite --manual-quotes
```

Существующая защищённая loopback-панель, opt-in POST preview. Пароль/ключи в URL
не передаются. Session/Bearer, exact Host/Origin, bounded JSON, read-only DB.
Матч и рынок должны совпасть с оригинальным seal; только FT_REGULATION_90,
подтверждённые rules, цена после seal, до kickoff, свежесть <=120s. Без действительной
калибровки и existing CORE readiness P/EV=NOT_VERIFIED. Даже арифметический EV
не создаёт решение и не снимает PASS: требуется существующий Service.decide
и новая независимая предматчевая перепроверка. Цена — OPERATOR_ASSERTION,
не заверенная котировка провайдера и не полный рыночный benchmark.

TRAIN → CALIBRATION → frozen FIT → новый HOLDOUT → evaluation остаётся исходным
протоколом. Минимум20/bin, ориентир60 CALIBRATION, минимум60 новых HOLDOUT.
Imported FT rows не становятся старыми prediction seals или HOLDOUT. При нынешних
данных Brier/LogLoss/ECE/market advantage не вычислены; все small markets SHADOW.

## Согласованный rollout / rollback (не выполнялся)

Точные production baseline: worker `42e25ccc0359f07937f1954b75edd61edacffc44`,
Render `srv-db2f000ae00c73a42sn0`, deploy `dep-db9qcdjrjlhs73fpkkcg`.
Кандидат публикуется только в существующий PR56, не в deployment branch/main.
После CI использовать ОДИН SHA из этого PR для всех перечисленных компонентов.

1. Согласовать отдельное окно обслуживания. Остановить scheduler/consumer,
   убедиться: очередь без PENDING/RUNNING, budget disabled/in_flight null.
   Сохранить checksums/counts очереди, revision59, бюджет, старые deploy IDs,
   хеши установленного gateway/relay **без значений auth**; приватный backup.
2. Проверить совпадение фактической SQL schema/ACL с кандидатом. Применить
   `supabase/migrations/20261017173910_sports_source_archive.sql` через утверждённую
   процедуру миграции. При дрейфе/активной очереди транзакция отказывает.
   Таблицы append-only/RLS, без прямого доступа service_role/anon; RPC parked.
3. Установить matched `server/sports_gateway.js` и `server/chat_store_gateway.js`,
   сохраняя существующее авторизованное auth enrollment штатной процедурой.
   Шаблоны fail-closed DEPLOYED_AUTH=[] не копировать как готовую production auth.
   Credentials не читать/не переносить через чат или Git. Бюджет не трогать.
4. После проверки RPC/template/config применить review-only activation SQL.
   Развернуть worker с того же SHA, существующий MCP launcher,
   `SEFIROT_CHAT_JOB_WORKER_MODE=sports_probe`, `SEFIROT_SOURCE_ARCHIVE=1`,
   read-only CORE, существующие имена relay/gateway environment references.
   Проверить Python3.14.3/full sources/status, source_status.ready, только одну
   live-инстанцию. Status не должен объявлять provider quota проверенной.
5. Только после отдельного разрешения исследовательского окна: enqueue через
   owner-only `select public.sefirot_plan_collection_day(39,2026)`, до5/day.
   Короткое окно бюджета/5 reserve/1min остаются прежними; автоматического
   возобновления разрешения на следующие сутки НЕТ. Нужна отдельно утверждённая
   политика ежедневного доступа, иначе честный статус PAUSED/QUOTA_STOP.
6. Проверить raw+links+dispatch hashes, job lease/completion, duplicate dispatch
   rejection без provider call, private export→QC→existing model input,
   budget/rows/snapshot неизменённые кроме разрешённых источников/квитанций.
   Расписание planner и read-only import можно включать лишь после этих проверок.

Rollback: остановить планирование/consumer, дождаться отсутствия in-flight;
выполнить review-only `20261017173910_source_archive_park.sql`, выключить worker
archive opt-in и вернуть зафиксированные baseline deploy/relay/gateway версии.
Не удалять source tables/links/dispatch, оригинальные queue rows и receipts.
Не восстанавливать квоту из старого backup и не очищать uncertain intents.
Старые seals открывать их старой сборкой; code_hash новой транспортной сборки
не разрешает автоматически переоформлять исторические денежные допуски.
