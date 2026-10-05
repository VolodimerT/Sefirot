# SEFIROT: актуальная база разработки

## Stake research odds bridge, 05.10.2026

Добавлен экспериментальный read-only источник Stake: `src/sefirot/stake_provider.py`,
`scripts/stake_snapshot.py`, `docs/STAKE_ODDS_PROVIDER.md`. Секрет читается только
из `STAKE_API_TOKEN`; в Git/receipt/error не сохраняется. Источник требует уже
существующий prematch seal, exact home/away/kickoff и сохраняет raw market names
без догадок о settlement. Статус строго RESEARCH_ONLY, monetary_permission=false,
execution_enabled=false. Причина: официальный Stake API подтверждает x-access-token,
но sportsbook GraphQL schema не является стабильным публичным контрактом.
4 boundary-теста нового провайдера прошли на Render. Живую авторизацию не считать
проверенной, пока токен не установлен в runtime environment; токен из чата в код
не переносить. Main не сливать.

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
