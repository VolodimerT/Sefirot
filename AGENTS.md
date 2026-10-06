# SEFIROT: актуальная база разработки

## Продолжение системы без API, 06.10.2026

API по указанию пользователя отложен. Cloud/keys не трогать в этом этапе.
Та же ветка / PR #11, main не сливать, дополнительных агентов не создавать.
См. docs/OFFLINE_WORKFLOW.md и docs/SYSTEM_REVIEW_20261006.md.
`work inbox --text` — существующий canonical file workflow: русский status/
карточка, named prediction_job_id → CAPTURE, прежний default main pool.
Файл quotes открывать после seal; timestamps не переписывать. Action +
jobs receipt + audit коммитятся одной transaction с nested savepoints.
Busy COMMIT -> rollback всей pending transaction, затем безопасный retry.
ERROR job -> exit 2; PASS решения остаётся нормальным результатом обработки.
Новые jobs receipts имеют RECORD binding; старые не переписывать.
report/accounting/replay/compare без rollback — только существующая ro БД;
backtest standalone. Обычных команд всё ещё 10: work вместо api-health,
последняя сохранена для явного вызова/--labs. Новый runtime не добавлен.
Модель/Policy прежние; math tests не доказывают forecast superiority.
Frozen effectiveness audit воспроизвёл 380 просмотренных historical TEST:
SoS кандидат 3/7 лучше, 4/7 хуже; KEEP_SHADOW. Не refit по этому TEST.
Локальный полный release 548/548; replay_matches/integrity=true. Проверки
Node handler не skipped. code_hash:
70aea1f55fbed4be9ef7bf10cbe3dbc627fa82debedea0787db3e2542d384b69.
CI сверять на конечном опубликованном head; API-срезы ниже
исторические. Новый server key проверен 06.10 23:08 Киев, по-прежнему
ACCOUNT_SUSPENDED; последнее server v11. Повторять API в этом этапе не надо.

## Уточнение доступа и минутной квоты, 06.10.2026 16:18 UTC

Та же ветка / PR #11, main не сливать; дополнительных агентов не создавать.
См. docs/API_ACCESS_RECOVERY_20261006.md. Свежий единственный provider status
подтвердил PROVIDER_ACCOUNT_SUSPENDED; исторические runner logs согласуются.
Это сообщение поставщика, а не установленная причина приостановки.
Обход/смену ключа/подписки не выполнять. Следующий sporting collection —
после восстановления доступа владельцем, новая bounded заранее назначенная
сессия. Старые REPORT/manifests/seals не переписывать под новый code hash.
camel-case errors.rateLimit теперь quota failure; отдельный числовой
x-ratelimit-remaining ограничивает минутные вызовы без auto retry/ожидания.
Дневной reserve сохранён; quota не резервируется глобально между процессами.
Server v9 побайтно сверён, временный auth удалён, исходный auth сохранён.
Полный локальный release 527/527; Python aggregate исполняет 19 Node groups.
Семь MODEL_MODULES и Policy неизменны. code_hash:
01d895ab7e2a09143c0dc11262fa52313c98e88462301436e6014067221597c9.
Server template SHA-256:
5f019b238bf8423879002f2040c617aef5fe4de3e86f9e5447e1795f7397b8f1.
Нижележащие 517/18, v6 и неустановленный account state — прошлые срезы.

## Проверенный шлюз и фактический отказ API, 06.10.2026

Та же feature/stability-reset-20261005/PR #11, main не сливать.
См. docs/GATEWAY_COMPLETION_20261006.md. server/sports_gateway.js —
канонический source template с пустой DEPLOYED_AUTH: fail closed.
При deployment приватно вставляются hashes прежнего runner credential;
compiled auth config и provider key в Git не помещать. API key остаётся
в существующем Vault/RPC, schema/подписка не менялись. Шлюз обновлён,
старый sefirot-debug-football заменён на HTTP 410 без I/O. Временный
credential проверки отозван, его файл удалён; исходный credential сохранён.
16 KB input/RPC, 2 MB upstream, 3/9 s timeouts, без redirects; exact
endpoint/params/count/paging, account redaction, numeric quota whitelist.
HTTP 200 + errors.access -> PROVIDER_ACCESS_DENIED; collector прекращает
последующие запросы. Не путать с неверным token/Free/expired: эти причины
не подтверждены. 06.10 15:31 UTC: final data-session одной заранее
объявленной cohort, 1 status attempt, 0 packets/fixtures/seals/forecasts.
api-health отдельно подтвердил отказ. Stake/Odds в этой среде не настроены;
исторический Stake 403 за 05.10 не считать свежей проверкой 06.10.
Локальный release: 517/517, demo/replay/integrity; один Python aggregate
исполняет 18 Node handler contract groups. CI явно ставит Node 22 во всех
4 Windows/Ubuntu × Python 3.11/3.13 jobs; CI сверять на exact final head.
Семь MODEL_MODULES/Policy прежние. Клиентский code_hash не включает JS
server: его SHA-256 отдельно указан в completion doc. HOLDOUT не пройден.
Нижележащие заявления «cloud не менялся» относятся к предыдущим срезам.

## Явная диагностика API, 06.10.2026

Та же feature/stability-reset-20261005: см. docs/API_HEALTH_20261006.md.
api-health --odds-provider stake выполняет один upcoming soccer catalogue
request, до пяти events в output helper, без UserIdentity/рынков/цен.
Наличие токена отдельно от HTTP 401/403/429 и fixed provider reasons.
Missing credentials: 0 requests. RESEARCH_API_READY не admission;
admission_ready/monetary_permission/execution_enabled=false. Default
The Odds API сохранён. Import-time Stake probe и raw debug errors удалены;
старые env flags не выполняют I/O и не открывают private messages.
19 новых offline контрпримеров; полный локальный release 510 тестов,
demo/replay/integrity успешны. MODEL_MODULES/Policy прежние, code_hash новый.
Настроенный облачный CLI этим изменением ещё не запускался; исторический
05.10 22:24 UTC Stake HTTP 403 не считать свежим статусом. Deployments
и секреты не менять молча. Current CI проверять на новом exact head.

## Ограничение сценария по DAILY AUDIT, 05.10.2026

Текущий head той же feature/stability-reset-20261005 продолжает STABILITY
RESET. См. docs/SCENARIO_CONSTRAINT_20261005.md: explicit sports-only
matchup_signal.value.selection_constraint.avoid_result=true, reliable/fresh
active FACT support. Запрет блокирует 1X2/DC/DNB/HANDICAP до ranking и
результатные Builder legs, сохраняется в research outputs. Добавление,
снятие или изменение содержания premises на recheck требует нового seal.
Нельзя превращать каждый проигрышный score branch в veto или выводить
restriction из коэффициента/прошедшего результата. Текст чата не parser.
Семь MODEL_MODULES и Policy неизменны; code_hash изменён. Старые seals
воспроизводить на архивной сборке. Draft PR #11 направлен в точную
feature/api-data-session-20261005, main не сливать. Дополнительных агентов
не создавать. Финансовые записи/исходные аудиты и личные receipts не
публиковать; external tip + filter не считать чистой модельной выборкой.

## Первый шаг STABILITY RESET, 05.10.2026

Текущая ветка: feature/stability-reset-20261005, поверх точного 8e6a3ab.
Карта зависимостей до изменений: reports/ARCHITECTURE_BASELINE_20261005.json.
Матрица всех modules/CLI, migration и предложенный accuracy protocol:
docs/STABILITY_RESET_20261005.md. Это не готовая 2.5-RC1 и не новая модель.
Один runtime sefirot.cli:main; launchers run_sefirot.py/SEFIROT_CORE.py
по умолчанию wrappers текущего CLI, прежние interfaces только --legacy.
В обычной справке 10 основных команд; --labs --help показывает все.
Старые явно вызванные команды сохраняются: help не является permission gate.
data-session по умолчанию cohort+baseline seals, без market/Builder grids;
они доступны только с --research-grids и lazy imports. build-info не
открывает БД/сеть и показывает code/model/policy identities. Model hash,
BASELINE_V1/STRICT, денежные caps и historical seals не менять.
Нижележащие разделы описывают исторические этапы; их старые hashes и
названия branch не заменяют текущую ветку. Main не сливать; секреты,
SQLite и личные receipts не публиковать. Дополнительных агентов не создавать.
Проверки: python test_sefirot.py и python scripts/verify_release.py.

## Единый API-сбор data-session, 05.10.2026

Продолжение в отдельной feature/api-data-session-20261005 поверх точного
Stake snapshot 2f9aa2a (tree c1290e7e1ebb4bec44cdfd9a3c2947477eca07ed),
включая CLI stake-snapshot. Активную feature/data-session-audit-20261004
меняет параллельная разработка: интеграция только fast-forward при
проверенном актуальном head; force/перезапись запрещены. data-session: status/quota → date fixtures →
reserve whole CALIBRATION cohort → one FT history request per league/season
→ capture → 50 main contracts + 14 goal builders. Sports gateway также
поддержан api-health/football-fetch; provider key остаётся серверным.
См. docs/DATA_SESSION.md. 26 новых offline контрпримеров; полный локальный release: 465 тестов,
demo/replay/integrity прошли; CI сверять на опубликованном head. code_hash:
415d924a4ab684df65dbdd829201dd5e5c0e83bdf5b55ad830998acabcfb04b6.
model_hash прежний. Реальный CLI упёрся в отсутствующий local/gateway
credential; подтверждённых API packets и новых реальных прогнозов нет.
Cloud gateway/Vault не изменены. Prices/approval/HOLDOUT/main merge не
выполнялись. Secrets/SQLite/личные packets в Git не помещать.

## Stake research odds bridge, 05.10.2026

Текущий рабочий контракт Stake подтверждён живым запросом. Старый draft
`sportsEvents` удалён из схемы; используется двухэтапный web GraphQL:
`SportTournamentFixtureList` -> exact fixture -> `FixtureIndexGroups` ->
`FixtureGroupMarkets`. Render smoke-test: token authenticated, 200 soccer
events, Nations League fixtures найдены; Cyprus-Latvia дал 14 groups / 292
markets. Добавлены `src/sefirot/stake_provider.py`,
`src/sefirot/stake_mapper.py`, `scripts/stake_snapshot.py` и CLI
`stake-snapshot`.

Mapper консервативно нормализует 1X2, Double Chance, DNB, BTTS, Asian Total и
Asian Handicap только на integer/half линиях CORE; quarter lines остаются raw и
отбрасываются из canonical main mapping. Small research mapping уже умеет
Match N+ shots, FT/1H total corners, FT/1H total cards (когда exact template
есть), team corner ranges. 8/8 dedicated provider+mapper tests прошли на
Render. Источник пока строго RESEARCH_ONLY:
freshness=RECEIPT_TIME_ONLY, settlement rules unverified,
monetary_permission=false, execution_enabled=false. Stake token хранить только
в STAKE_API_TOKEN и перед production использованием перевыпустить токен,
который когда-либо публиковался в чате. Main не сливать.

## Сравнительный обзор и forward-scorecard, 05.10.2026

Первый шаг после обзора: read-only forward-scorecard всей заранее
назначенной API-выборки. Original raw/base, reliability bins и слабые
neutral/frozen-history ориентиры, пропуски в знаменателе; рынок БК
не подменяется baseline. Старые CLI-only builds можно читать при
совместимом model_hash, но нельзя пересчитывать/переподписывать seals.
См. docs/DEVELOPMENT_REVIEW_20261005.md и docs/FORWARD_SCORECARD.md.
22 новых теста; всего 431, точный release/CI сверять на текущем head.
code_hash: eb9031299936744cf2b3faa809949bce42c584a466fac4da4c0ea4f71bdf18de.
model_hash прежний. Реальная сохранённая выборка: 0/17 scored,
17 последних INSUFFICIENT_HISTORY. Никакой новый holdout/approval,
main merge или вероятность малых/Builder markets не заявлены.


## Новый аудит Builder, 05.10.2026

Добавлены builder-grid/compare-builder: 14 заранее фиксированных
push-free голевых сочетаний, совместная raw вероятность по клеткам
BASELINE_V1, history/rate sensitivity; совместная API-цена не
подменяется произведением цен одиночек. small-market-review проверяет
full-time API статистику, непересекающиеся long/recent, shrink,
venue/outlier и allowed baseline следующего соперника.
Все новые режимы D/stake=0, вероятность малых линий пока не моделируется.
ticket-audit добавляет категории MAIN/SMALL/BUILDER/UNMAPPED.
См. docs/BUILDER_AUDIT_20261005.md. Локально 409 тестов и release gate.
code_hash: e8af27bcbe6d5d1e4508f0529a41623282bcd1da88780f6eb906749731d46499;
model_hash прежний. Старые seals/планы не переподписывать. Main не сливать.
Личные билеты/API-пакеты в Git не помещать. CI сверять на новом head.


## Сбор будущей API-выборки, 05.10.2026

Добавлены forward-plan/capture/settle/status. Документация:
`docs/FORWARD_COLLECTION.md`. 382 локальных теста и release gate прошли;
CI сверять на новом head. code_hash:
`28d99e80359ff84329e918ba76a96357384c0b8f138b4be7572f6edf9941dd03`.
model_hash прежний. Коллектор BASELINE_V1, фиксированные семь DEFAULT_POOL
контрактов, research ledger без production routes. HOLDOUT только после
frozen nonsynthetic calibrator, без fit_ids overlap; план не сертификат.
Реальный API на 5 октября: 99 NS, 17 заранее зарезервированных CALIBRATION,
17 INSUFFICIENT_HISTORY, 0 seals/results. Свежая история 2026 отклонена Free;
Odds API key отсутствует в проверенных конфигурациях. Никаких новых approvals,
LIVE или main merge. Частные API packets/SQLite не добавлять в Git.

## Продолжение по аудитам 02–03 октября, 04.10.2026

Добавлены `goal-robustness` и `compare-robustness`: фиксированные raw-пробы
удаления крупнейшего target-выброса и ограничения недавних всплесков,
сравнение всех 50 контрактов с API-квитанцией, D/stake=0. Карточка,
readiness и session показывают паспорт сборки, стадии и очередь действий.
Документация: `docs/AUDIT_FOLLOWUP_20261004.md`. 361 локальный тест и
release gate прошли; удалённый CI сверять на новом head.
code_hash: `95188a425b59470f8aef3030e977aa994361a8722705c4dfb1fd436d002e40ac`;
model_hash прежний. BASELINE_V1/STRICT и денежные caps не изменены.
Контрфактические пробы не переписывают спортивные факты или исходный seal,
не являются обученной моделью, доверительным интервалом или денежным допуском.

## Рабочее обновление 04.10.2026: данные, сессия, билеты

Продолжение от `d665237` находится в `feature/data-session-audit-20261004`.
Архив уже полученных API-пакетов, coverage по командам, read-only `session`
и `ticket-audit` описаны в `docs/OPERATIONS_UPGRADE.md`. Локально 343 теста,
release gate, три реальных research seals из сохранённого API-снимка и
price-blind сетка 50 контрактов проверены; monetary_permission=false.
code_hash: `718c88f2e6073aca9a532f90a436af5bf884a6e002e25c59438c4fa00fd4a007`;
model_hash прежний. Старые seals/approvals не переподписывать.
Обновление опубликовано в этой feature-ветке; черновик PR #9 направлен
в `core242-version-audit`. На коммите `c4d5fcf` все 343 теста и полный demo
прошли в GitHub Actions на Windows/Ubuntu с Python 3.11/3.13.
Ошибка записи 403 устранена 04.10.2026 установкой ChatGPT Codex Connector
на аккаунт владельца только для `Sefirot`; запись через connector проверена
публикацией этого обновления документации. Первоначальная публикация была
через GitHub UI. Для продолжения выбирать feature-ветку и сверять build hash;
CI проверять на последнем коммите. `core242-version-audit` сохраняет прежний срез.
API-Football реально отвечает, однако свежая история нужного сезона
ограничена тарифом и коэффициенты не подключены. Накопление доступных
наблюдений не заменяет недоступный прошлый сезон или текущую форму.
Личные входы/выходы ticket-audit и SQLite проверок в Git не помещать.

## Локальный кандидат 04.10.2026: расширение основных рынков

В feature-ветке `feature/main-market-expansion-20261004` подготовлен пакет
поверх `cb07ebb`: импорт шести семейств котировок и price-blind research
сетка из 50 контрактов. См. `docs/MAIN_MARKET_EXPANSION.md`.
code_hash кандидата: `0aa60458958310628f3fbbd6e0523c03e90e16bb97f984a3d134a4320a93f290`;
model_hash сохранён. Локально 314 тестов, release gate успешен.
Этот промежуточный срез включён в `feature/data-session-audit-20261004`;
отдельная исходная ветка остаётся локальной. Расширенную сетку не передавать
в денежный admission: она RESEARCH_ONLY, stake=0. Получение реальных
коэффициентов не подтверждено; sports API проверен в следующем срезе выше.

## Опубликованная база

Архивная база обновления — CORE 2.4.2 в ветке `core242-version-audit` репозитория
`VolodimerT/Sefirot`. `main` пока содержит CORE 2.3; ветка
`core24-decision-finalizer` и её PR #7 содержат старую CORE 2.4.0.
Не выбирать их молча как основу нового расчёта или исправления.

В рабочую 2.4.2 добавлена оптимизация 03.10.2026: см.
`docs/RUNTIME_OPTIMIZATION.md`. Тег `v2.4.2` сохраняет исходный архивный
срез. Для новых расчётов выбирать текущую ветку; сверять build hash,
а не только одинаковый номер версии. Актуальный code_hash:
`49fbf90cc34c53dfaddf052f7fe1000095913d45a9963ed9b3758355ad04905d`.
До просьбы обновить коэффициенты проверить `readiness` сохранённого прогноза.

Перед работой проверить ветку, `VERSION` в `src/sefirot/contracts.py`,
`pyproject.toml` и `docs/HANDOFF_CORE_24.md`. Воспроизведение старого решения
выполнять на его архивной версии; seals, approvals и fitted-артефакты
не переподписывать новой сборкой.

Сохранить Конституцию, девять сефир в одном процессе, прематчевый режим
и стандарт BASELINE_V1/STRICT. LIVE, догон, автоматическое размещение
ставок и Tavily не добавлять. Не создавать дополнительных агентов.
Ключи и личные журналы в Git не помещать.

Независимый prospective holdout новой модели ещё не пройден. В `main`
не сливать до выполнения ранее согласованной проверки или нового явного
решения владельца. Исторический просмотренный TEST не использовать
для подбора порогов. Успешные программные тесты не доказывают доходность.

Текущие проверки: `python test_sefirot.py` и
`python scripts/verify_release.py`. Сохранённый итог оптимизации: 297 тестов,
demo/replay/целостность; подробности в `reports/RELEASE_CHECK.json`.
Замеры до/после — `reports/RUNTIME_BEFORE.json` и `RUNTIME_AFTER.json`.
Кеш целостности привязан к свежим байтам каждой записи; не заменять его
кешем полного journal_ok или разрешений. Подмена извне обязана обнаруживаться.
