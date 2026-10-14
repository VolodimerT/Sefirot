# Безопасный режим чтения перед разрешённым runtime rollout

Продолжение единого CORE 2.4.2 кандидата в draft #56, после
`79c7c5b4c9c5e8b0a10471e38956f83bf046d145`. Production не изменяется
этим PR; режим пока подготовлен и проверяется локально/CI.

## Подтверждённые препятствия

При наличии `SEFIROT_STORE_URL` прежний `chat_mcp.main` всегда запускал
chat_queue worker и мог создать первый cloud checkpoint. Старые
`status/report` открывали Repository writable и меняли SQLite header,
хотя не добавляли новые прогнозы. У MCP доступны capture/decide/result;
наследуемые HTTP routes тоже должны подчиняться запрету записи.
Поэтому запуск такой сборки для предварительного чтения не гарантировал
отсутствия очереди, forecast mutations или provider jobs.

Девять первых методов на прежних scripts дали 21 assertion failure,
включая различие исходных SQLite bytes и автоматический старт worker.
Итоговый набор содержит десять новых методов, в том числе настоящие
authenticated loopback HTTP requests и отдельные owned SQLite databases.
Source/auth/queue/store callbacks synthetic, настоящие ключи/провайдеры
не используются. Сохранены исходные MCP/HTTP/queue проверки.

## Гарантии явного режима

Оператор может выбрать **`SEFIROT_BRIDGE_READ_ONLY=1`**. Отсутствующее
значение или точное `0` сохраняет прежний research режим. Любое другое
значение отказывает до credentials, startup smoke и bind; опечатка не
должна превращаться в разрешение записи.

- Gateway разрешает только чтение original status/report/decision.
  Остальные операции отказывают до restore, checkpoint, Repository,
  Service и provider dispatch. Внутренний probe entry защищён отдельно.
- Repository открывается read-only; verify и дальнейшее чтение используют
  один BEGIN snapshot. Missing ledger отказывает, parent/DB не создаются.
- MCP публикует только sefirot_status/sefirot_report. Прямой tools/call
  остальных операций тоже отказывает. REST capture/decide/result не могут
  обойти gateway guard; публичный GET demo в этом режиме запрещён.
- Worker не запускается. Даже прямые chat_queue.process_one/run/start
  не claim/complete jobs и не создают фоновый поток.
- При bootstrap нужен существующий проверенный durable checkpoint;
  revision 0 отказывает до первого save. Pending jobs остаются нетронутыми.
- Startup smoke использует прежнюю явно синтетическую owned temporary
  database; он не создаёт новый канонический прогноз или денежный допуск.

Авторизация прежняя, никакие существующие значения секретов не считываются
инструментами и не меняются. Original PASS/BET можно читать как историческое
решение; нового решения/ставки/fit этот режим не создаёт.

## Конкретный production переход — только после отдельного разрешения

Целевой существующий сервис: `sefirot-strict-double-v2-20261006`,
service ID `srv-db2f000ae00c73a42sn0`. Проверенная management configuration:
branch `feature/stability-reset-20261005`, autoDeploy=no,
start command `python scripts/strict_double_20261006_v2.py`,
build command `pip install . flask`. Ничего из этого не менялось.

1. Владелец отдельно разрешает изменение production и краткое прерывание
   старого worker. Сохранить revision 59/queue и согласовать остальные
   legacy consumers по уже подготовленному перечню 25 сервисов. Общий
   gateway budget оставить PAUSED; не выполнять pending sports_probe.
2. Выбрать в Render уже проверенную candidate branch
   `feature/situation-integration-20261013` и **точный head из final CI**.
   Ветка/commit не подменяются названием CORE 2.4.2. AutoDeploy оставить no.
   У текущего MCP-коннектора нет аргумента commit SHA в trigger_deploy и
   нет операции update service branch/suspend. Владелец использует Dashboard
   для этих действий; исходную legacy Git branch не передвигать ради Render.
3. Только в разрешённом scope установить merge двух non-secret flags:
   `SEFIROT_BRIDGE_MODE=mcp`, `SEFIROT_BRIDGE_READ_ONLY=1`.
   Не заменять весь env набор, не копировать/читать secret values.
   Переход на `READ_ONLY=0`, источники, ставки и запуск очереди не разрешены
   данным планом. Deployment trigger до branch/head/flag проверки запрещён.
4. При отдельно разрешённом deployment подтвердить deployed SHA == CI SHA,
   runtime build hashes, READ_ONLY mode, verified original checkpoint и
   WORKER_DISABLED. Проверить authenticated original status/report, denied
   mutators, отсутствующие новые queue leases/checkpoints/provider attempts.
   Synthetic CI не считается этой реальной cloud проверкой.
5. Для rollback сохранить budget PAUSED и worker disabled. Владелец сначала
   останавливает потребителей; старый код может игнорировать новый flag и
   вновь запускать worker. Не делать автоматический downgrade/deploy/retry.

Этот flag защищает только bridge runtime, не account-wide legacy scripts.
Deploy/config/stop/secret access/provider requests в данном этапе не были
разрешены или выполнены. Реальный CAL/HOLDOUT по-прежнему требует указанной
лиги/сезона, разрешённых original sources и prospective registration.
Данные не выдуманы, протокол DRAFT_NOT_REGISTERED, **PASS, stake=0**.

## Проверки

`python -m unittest tests.test_bridge_read_only_rollout tests.test_chat_mcp
tests.test_chat_gateway tests.test_chat_queue -v` — 26 методов.
Полный release и четыре OS/Python plus actual PostgreSQL mirror/budget CI
проверяются на точном финальном коммите draft #56. Все src/model/Policy,
старые reports/fixtures/source seals и независимый protocol неизменны;
scripts имеют отдельные SHA256. Реальный hosted Android не проверен.
