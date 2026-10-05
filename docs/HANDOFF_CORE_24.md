# SEFIROT — продолжение разработки

## Текущий этап: STABILITY RESET, 05.10.2026

Рабочая ветка feature/stability-reset-20261005 от 8e6a3ab; VERSION остаётся
2.4.2, точное поведение сверять через `sefirot.py build-info`.
Карта всех 55 исходных модулей, матрица 52 старых команд, migration и
предложенный будущий baseline/DC protocol: STABILITY_RESET_20261005.md.
Default data-session не создаёт 50-contract/Builder grids; прежний путь
включается `--research-grids`. В справке 10 основных команд, полный
compatibility/LABS список `--labs --help`. Оба старых launcher-а по
умолчанию запускают canonical CLI; исторические интерфейсы требуют
первый флаг --legacy. Legacy-код не удалён. Ниже — исторические этапы.
Новая модель, реальная API-выборка, прибыльность и monetary approval этим
шагом не подтверждены. Main merge не выполнять.

## Единый API-сбор, 05.10.2026

Изолированная feature/api-data-session-20261005 включает Stake snapshot
2f9aa2a, CLI stake-snapshot и data-session. Документация: DATA_SESSION.md. Один запуск
фиксирует весь CALIBRATION cohort до истории/forecast, ограничивает квоту,
собирает историю один раз per league/season и создаёт 50 main/14 goal Builder
research contracts на каждый пригодный prematch seal. Пропуски остаются
в знаменателе. api-health и football-fetch поддерживают существующий gateway.
26 новых контрпримеров; 465 локальных тестов и release прошли;
CI сверять на опубликованном head.
code_hash: 415d924a4ab684df65dbdd829201dd5e5c0e83bdf5b55ad830998acabcfb04b6.
model_hash прежний. В этом runtime local/provider key и gateway runner
token не настроены: нового живого API-capture нет. Vault key и существующий
gateway подтверждены только метаданными, cloud не менялся. Stake источник
сохранён; интеграция в параллельную feature/data-session-audit-20261004
только fast-forward при сверенном актуальном head, без force. Main, monetary approval и HOLDOUT не выполнены.

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
`FORWARD_COLLECTION.md`. 382 локальных теста и release gate прошли;
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

## Последнее продолжение 04.10.2026: практические функции

`feature/data-session-audit-20261004` продолжает `d665237`. Добавлены
`football-archive`, `football-from-archive`, `session`, `ticket-audit`;
контракты и команды — `OPERATIONS_UPGRADE.md`. 343 локальных теста и
release gate прошли. Три реальных API research seals, групповая готовность
и сетка 50 контрактов проверены на уже полученном спортивном ответе;
все три матча остаются BLOCKED_BEFORE_PRICE. Денежного допуска нет.
code_hash `718c88f2e6073aca9a532f90a436af5bf884a6e002e25c59438c4fa00fd4a007`,
model_hash прежний. Архив не выдумывает составы/контекст или свежую историю.
Личные билеты сохраняются отдельно от Git. Обновление опубликовано в
`feature/data-session-audit-20261004`; черновик PR #9 — к `core242-version-audit`.
На `c4d5fcf` все 343 теста и полный demo прошли на Windows/Ubuntu с Python
3.11/3.13. Ошибка GitHub connector 403 устранена 04.10.2026: приложение
установлено на аккаунт владельца только для `Sefirot`; реальная запись
проверена обновлением этой документации. CI сверять на последнем коммите.
Реальный API-Football подключён 04.10; история требуемого сезона ограничена
Free, The Odds API не подключён. Старое описание отсутствия обоих ключей
ниже фиксирует состояние предыдущего среза, а не последней проверки.

## Локальный кандидат 04.10.2026

Расширение основных API-рынков и фиксированная исследовательская сетка
описаны в `MAIN_MARKET_EXPANSION.md`. База — оптимизированный `cb07ebb`;
feature-ветка `feature/main-market-expansion-20261004`. 314 локальных тестов
и release gate прошли; code_hash
`0aa60458958310628f3fbbd6e0523c03e90e16bb97f984a3d134a4320a93f290`.
model_hash прежний `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`.
Денежные правила не расширены. Промежуточный пакет включён в рабочую ветку
`feature/data-session-audit-20261004`; отдельная исходная ветка локальная.
На момент этого раннего среза запись GitHub connection возвращала 403 и ключи отсутствовали;
актуальный sports API статус указан выше. Получение коэффициентов не проверено.

## Актуальный срез 03.10.2026: CORE 2.4.2

Текущая рабочая сборка включает оптимизацию 03.10.2026 без нового номера
версии и без нового PR. Исходный тег `v2.4.2` остаётся архивом до оптимизации.
Применять текущую ветку `core242-version-audit`; паспорт сборки и замеры —
`RUNTIME_OPTIMIZATION.md`. Новый code_hash:
`49fbf90cc34c53dfaddf052f7fe1000095913d45a9963ed9b3758355ad04905d`;
model_hash:
`46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`.
297 тестов, demo/replay/целостность проходят. Перед запросом новой цены
проверять `readiness`: недостаток калибровки/holdout цена не исправляет.
Вероятности в benchmark совпадают; изменение исходников `_payoffs.py`
меняет model_hash. Старые fitted-артефакты автоматически совместимыми
не объявлять, не переподписывать. Новое прогнозное преимущество не заявлено.

Рабочая ветка для продолжения — `core242-version-audit`, CORE 2.4.2.
Она основана на опубликованном
финализаторе `0e390683` и интегрированном архиве CORE 2.4.1. Дополнительная
проверка 16 старых сборок выявила ещё четыре дефекта, исправленных в 2.4.2:
пригодность независимых FACT и market_news, согласованность PUSH-риска
решения и записи исполнения, совпадение build/policy при SYSTEM_RECOMMENDATION.
Подробности — `docs/CORE242_VERSION_AUDIT.md`, регрессии —
`tests/test_version_audit_regressions.py`. Финальный локальный release gate:
274 теста, demo/replay/целостность, 12 синтетических матчей/84 рынка,
49 ретроспективных случаев. Статус удалённого CI проверять на точном
опубликованном коммите: старый зелёный CI версии 2.4.0 его не заменяет.

GitHub main остаётся CORE 2.3 `96dd958`; PR #7 содержит старую CORE 2.4.0.
Для новых работ выбирать `core242-version-audit`, не `main` или PR #7.
Перед расчётами проверить VERSION=2.4.2 и актуальный identity выше.
Исходный code_hash архивной 2.4.2 до оптимизации:
`cff8f1021dd1f308e70cfced313ba37b461758a4b02142ad2c21321819968b50`.
Не считать состояние удалённого репозитория равным скачанному архиву
без проверки опубликованных файлов. Прогнозное улучшение P0 не доказано;
BASELINE_V1/STRICT, research-policy-v3 и Конституция сохранены.
Старые fitted-артефакты/разрешения не переподписываются новой identity.

## История P0 и ограничения

Не переписывать систему с нуля. Репозиторий `VolodimerT/Sefirot`.

Уточнение базы: CORE 2.1 `cf4dca029faf420542d361266d87ac46f0d0d822` уже имеет продолжение CORE 2.3 `96dd95861be6c11bbc450432ca280f9a4d2efd3f` в main. От него создана локальная feature-ветка `feature/p0-sos-threshold-validation` с исследовательским CORE 2.4. Не откатывать main на старый CORE.

Правила: Конституцию не менять, девять сефир не размножать, LIVE/догон не реализовывать, Tavily пока не подключать. Ключи в файлы, ответы и Git не помещать.

Свежий источник задачи — `SEFIROT_AUDIT_2026-09-30_AND_UPGRADE_PLAN.md`. Его исходные финансовые записи в публичный Git не перенесены. Реализация и методика: `docs/P0_UPGRADE_CORE_24.md`.

P0 дополняет CORE 2.3: реальные SoS weights в вероятности, trained count bins 0/1/2/3+, отдельные profile priors, graded admission с holdout класса, configured reference-book consensus и автоматически обогащаемый settlement/audit. BASELINE_V1/STRICT остаётся стандартной политикой; кандидат не объявлен лучше.

Сначала проверить `python test_sefirot.py`, затем текущий diff и сохранённые отчёты. Feature не сливать в main: историческая проверка уже просмотренного TEST дала смешанный результат, нового prospective holdout ещё нет. Для TEAM_TOTAL Brier немного ниже, интервал включает отсутствие улучшения; 1X2 и four-count metrics хуже. Не настраивать пороги по этому TEST.

Следующий кодовый этап — нормализованный источник API-Football через `API_FOOTBALL_KEY`, уже подготовленный владельцем. Нужны реальные предматчевые snapshots и будущий holdout. Модуль источника не должен вносить цены в Probability до seal, придумывать FACT или импортировать live для допуска.

Историческая блокировка connector (`403 Resource not accessible by integration`)
была обойдена публикацией через браузер после разрешения владельца.
Владелец также разрешил публикацию исправленной 2.4.2. Продолжать от ветки
`core242-version-audit`; отсутствие права записи у connector не означает,
что исправленная версия отсутствует в GitHub. В main не писать до
согласованной независимой проверки.
