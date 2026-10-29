# Recovery & Research Pipeline v1.0 — 18.10.2026

База этого ремонта: PR56 HEAD `b6650b271749bcd43c60f7a5ac96ab6fa9d7e9d1`.
Все четыре tests/shared-provider-budget runs на push/pull_request проверены
повторно: success,20/20 checks. Между c558486 и b6650b27 два намеренных изменения:
e5146b5 (автосбор/архив/QC/модельные входы) и b6650b2 (защита имён полей).
История не переписана; snake_case xG/goals_prevented и безопасная диагностика
сохранены. Этот ремонт создаёт следующий проверяемый PR-head, не deployment.

## Строгое решение о деплое

Владелец разрешил деплой только при PR56 HEAD=c558486a290362e0924fcbfdac2a51e47ae5df63
и Render branch=42e25ccc0359f07937f1954b75edd61edacffc44, успешном exact-head CI,
fast-forward и подтверждённых правах. Фактический HEAD отличается уже в начале
этапа. Поэтому **PASS / NO DEPLOY**, даже при зелёном CI и возможном fast-forward.
Не откатываем PR и не выдаём новый HEAD за разрешённый. Main, Render-ветка,
production code/SQL schema и secrets этим ремонтом не обновляются.

Render: srv-db2f000ae00c73a42sn0, workspace tea-d85icff7f7vs73ao7shg,
branch feature/stability-reset-20261005, live42e25ccc, autoDeploy=no,
1 Free web instance. Реальный GET /health вернул200, worker_running=true,
sports_probe,core_read_only=true и exact live SHA. /status без авторизации401.
Первый health запрос попал в холодный запуск, а не доказанный crash. По текущим
Render docs Free web service засыпает после15 минут без входящего трафика;
background polling не означает постоянную доступность. Периодический keepalive,
новый сервис, restart и платный upgrade не создавались.

## Подтверждённый дефект и ремонт

Контрпример на неизменённом b6650b27: первый statistics packet нарушает
SOURCE_SAFETY, но collect помечает его DONE и выполняет второй provider fetch.
Получено2 вызова вместо1; значения неизвестных полей уже не раскрывались,
но квота могла расходоваться дальше. Отдельно отказ Gateway терял классификацию
SOURCE_SAFETY и выглядел общей транспортной ошибкой.

Теперь SOURCE_SAFETY завершает batch с ERROR до следующего запроса. В ответе
нет rows/count/projection/source_packet; остаются безопасные metadata, receipt
(когда он получен) и отфильтрованные bounded имена неподдерживаемых статистик.
Предыдущие безопасные оригинальные packets не меняются и не теряются.
Перед persistence sink небезопасный источник отсекается. Gateway архивного
режима возвращает тот же безопасный код/имена без значений и завершает protected
reservation с FAILURE. SDK сохраняет тип ошибки и закрывает ответ; повторов нет.
Нормализованные чувствительные имена, включая пробелы/пунктуацию, не попадают
в hints. Поддерживаемые snake_case метрики, receipts/hashes, модель и Policy
сохранены. Worker/lease/restart и прежние quota guards не переписаны.

## Хранение и временные границы

Используем прежние queue source_packet + существующий source Repository,
SHA256/QC/export_sports/review_small_market. SQL sports_archive в кандидате
остаётся подготовленным; production-миграция не запускалась. Из compact rows
никаких «оригиналов» не восстанавливаем. Status account fields не сохраняются.

Coverage добавляет раздельные temporal_source_views с ссылками на неизменённый
source_id: PREMATCH (NS и provider/local-QC knowledge до kickoff), POST_FT
(FT и не раньше90 минут после kickoff), HISTORICAL_NS (поздно импортированное NS),
OTHER. Поздний импорт старой NS-квитанции не становится предматчевым seal.
Это логические представления существующего архива, не новый модельный движок.

## Разрешённый ограниченный live pilot

Новое задание прямо предусматривает EPL39/2026 через существующий worker/Gateway.
Штатная postgres-only arm_research_budget(5,12) открыла одно окно 09:11:34–09:23:34UTC.
Тело установленной функции совпадает с tracked SQL SHA256
b43812d05986f6009cc174dfa021fd9817734963eedf66677363b712f9635895.
Не делали прямых UPDATE лимитера, reset/refund/очистку истории или повторный arm.
Перед каждым заданием проверяли enabled/expiry/in-flight, минутный интервал,
остаток, предыдущее завершение и сохранность оригинального packet.

1. /status: genuine200,18.10 09:12UTC, Pro active,7500/day.
2. /fixtures date2026-10-18 league39 season2026:4 NS fixtures до kickoff.
3. /fixtures date2026-10-19 league39 season2026:1 NS fixture до kickoff.
4. /fixtures id1557421: подтверждён FT,league39/season2026,home52/away65,
   kickoff2026-10-11T13:00Z,счёт3:1. Старый orphan statistics не объявляли
   подтверждённым FT без этого нового независимого fixture binding.
5. Свежий FT statistics packet получен09:20:27UTC:2 team rows, source archived.
   Всего5 genuine calls,5 DONE/attempt1. Provider remaining7496/7500;
   protected budget самостоятельно QUOTA_STOP/disabled,remaining5=reserve5.
   В очереди8 source_packet; originals сохранены и независимо хешированы.

Все запросы идут через тот же shared PostgreSQL budget. Последующие окна или
автономное ежедневное arm не включены. /status запрос может иметь иной учёт
у провайдера: фактические upstream обращения считаем по sports_attempt и receipts,
а provider remaining/current показываем отдельно с временем наблюдения.

На настоящих новых пакетах воспроизведён второй дефект: более ранняя статистика
до первой известной FT-квитанции делала invalid весь fixture, включая свежий
post-FT ответ. Coverage показывал0 корректных statistics и мог планировать
лишний fetch. Исправление исключает только старую неподтверждённую версию из
расчёта, сохраняя её raw record/reason. Новая post-FT версия проходит QC;
конфликты команд/значений между допустимыми post-FT версиями всё ещё отклоняются.
Ни старые, ни новые источники не переписаны. Проверено без новых API calls.

## Калибровка и проверки

Исходный TRAIN→CALIBRATION(validation)→frozenFIT→новыйHOLDOUT протокол и gate
сохранены.20 независимых матчей/bin,ориентир60 CALIBRATION,минимум60 HOLDOUT.
Один новый FT результат не образует независимую калибровку или исторический
прогноз. Реальный fit, cohort registration и HOLDOUT задним числом не выполняются.
Brier/LogLoss/ECE/рыночный benchmark — NOT_VERIFIED до соответствующих seals,
результатов и полного набора независимых наблюдений. PASS/stake0; малые SHADOW.

Новые regressions проверяют stop-after-safety, сохранение предыдущего оригинала,
невызывание sink, safe hints/SDK errors, прежние xG hashes и поздние NS imports.
Настоящий SQL arm проверен на изолированном PostgreSQL WASM и теми же SQL cases
в native provider-budget CI: owner ACL,5/day,12min,1/min,reserve5,no auto-arm,
active-window/in-flight refusal,пределы параметров и сохранение attempt history.
Это изолированные проверки кода, не подмена реального API; live pilot доказан
отдельными настоящими receipts/queue jobs. Exact-SHA CI и полный Python3.14.3
release gate нового коммита фиксируются в итоговом отчёте.

P0: отдельное согласование разрешённого SHA для matched rollout; затем SQL archive
и установленный stop/diagnostics. P1: полный календарь/предматчевая история,
coverage/QC и независимые последовательные выборки. P2: согласованная ежедневная
доступность scheduler/consumer в существующей инфраструктуре и операторский UI.
Ни один из этих пунктов не означает Stake/BET или финансовое разрешение.
