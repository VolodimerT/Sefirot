# SEFIROT: ревизия архитектуры и первый шаг стабилизации

Дата: 05.10.2026, Europe/Kyiv. Основа: `8e6a3ab81b93ecc0a0c64b57fc294176f016cff1`,
tree `327a7e940928274f9fc5dc505558cf7b72df86b1`, CORE 2.4.2.
Рабочая ветка продолжения: `feature/stability-reset-20261005`.

Изучены новый STABILITY MINI AUDIT, DATA SESSION UPDATE, COMPARATIVE REVIEW,
BUILDER UPDATE и DAILY AUDIT за 04.10, AUDIT FOLLOWUP и DEVELOPMENT за 04.10.
Две копии DAILY AUDIT — один источник. Личные билеты и сами аудиты в Git
не переносятся. Отрицательный результат восьми билетов не доказывает,
что модель неверна; положительный блок основных рынков не доказывает edge.

## 1. Карта конфликтов до изменения кода

Машинная карта всех импортов, входящих зависимостей, исходных SHA256,
повторяющихся имён функций и CLI: `reports/ARCHITECTURE_BASELINE_20261005.json`.
Это статический анализ всех scopes, а не измерение исполнения. Совпадение
имени функции не доказывает идентичность её поведения.

Подтверждённые размеры: 44 canonical + 11 legacy Python-модулей,
52 CLI-команды, 31 документ, 29 test-модулей.

| Пересечение | Факт по коду | Решение первого этапа |
|---|---|---|
| Два пакета | `src/sefirot` не импортирует `sefirot_core`; legacy используется отдельными launchers, семью тестовыми файлами и `scripts/capture_snapshot.py` | Один текущий runtime `sefirot.cli`; legacy сохраняется для явного исторического воспроизведения |
| Три launcher-а | `sefirot.py` ведёт в canonical CLI; два других после предупреждения всё ещё запускают другое ядро | По умолчанию все launchers ведут в canonical CLI; старые интерфейсы доступны только с `--legacy` |
| 52 команды | Одна плоская справка смешивает сбор, решение, fitting, Builder, cloud и governance | 10 основных команд в обычной справке; `--labs --help` открывает всю compatibility-поверхность |
| Ежедневный сбор | `data_session` напрямую импортирует и создаёт 50-contract grid и 14 Builder после каждого seal | По умолчанию только cohort и baseline seals; сетки требуют `--research-grids` |
| Несколько sports routes | `football-fetch/normalize/archive/from-archive` — полезные низкоуровневые инструменты, `forward-*` — стадии той же выборки | Единственный daily entrypoint `data-session`; инструменты не удаляются |
| Дрейф инструкций | README рекомендует старую feature-ветку; номер 2.4.2 не различает поведение | Актуальный branch + `build-info` с code/model/policy identities |
| Повторные расчёты | Legacy и canonical markets/model/storage имеют разные контракты и разные журналы | Не объединять dataclasses, SQLite или seals по одинаковому названию |
| LABS в прогнозе | `engine.prepare` и `Service.capture` не импортируют Builder/small-market/cloud; SoS — отдельный существующий fitted режим | Не менять модель, routing, grants или исторические артефакты |

## 2. Матрица модулей

Один статус назначен каждому файлу исходной сборки. MERGE означает будущую
проверку интерфейса, а не разрешение сейчас переписать sealed contracts.

| Статус | Canonical modules (`src/sefirot/*.py`) |
|---|---|
| KEEP_STABLE | `__init__`, `_payoffs`, `api_health`, `contracts`, `credentials`, `data_session`, `decision_card`, `engine`, `evaluation`, `evidence`, `feedback`, `football_gateway`, `football_provider`, `forward`, `forward_scorecard`, `identity`, `markets`, `odds_provider`, `probability`, `provider_transport`, `repository`, `risk`, `service`, `sports_archive` |
| MERGE | `action_plan`, `cli`, `readiness`, `session`, `worker` |
| MOVE_TO_LABS | `backtesting`, `builder_research`, `cloud_sync`, `diagnostics`, `fixtures`, `goal_model`, `goal_research`, `goal_robustness`, `market_grid`, `research`, `retrospective`, `small_market`, `stake_mapper`, `stake_provider`, `ticket_audit` |

`goal_model` пока остаётся физически на прежнем месте и в model identity:
его validate/estimate contracts используются canonical probability.
MOVE_TO_LABS — статус эксперимента, не требование немедленно переносить файл.

| Статус | Legacy modules (`src/sefirot_core/*.py`) |
|---|---|
| DEPRECATE | `__init__`, `audit`, `backtest`, `capture`, `core`, `governance`, `market_link`, `markets`, `model`, `storage`, `system` |

Ни один модуль сейчас не получает DELETE_AFTER_MIGRATION: ещё существуют
legacy потребители и исторические журналы. Удаление — после отдельной
миграции пользователей, с сохранённым архивным исходным кодом.

## 3. Матрица команд и входов

KEEP_STABLE — основная поверхность, не сертификат прибыльности.

| Статус | Команды |
|---|---|
| KEEP_STABLE | `build-info` (новая read-only identity), `api-health`, `data-session`, `capture`, `readiness`, `fetch-odds`, `decide`, `forward-settle`, `forward-scorecard`, `verify` |
| MERGE | `work`, `result`, `closing`, `replay`, `explain`, `session`, `reserve`, `forward-plan`, `forward-capture`, `forward-status`, `odds-events`, `football-fetch`, `football-normalize`, `football-archive`, `football-from-archive`, `report`, `accounting` |
| MOVE_TO_LABS | `demo`, `fixture`, `ticket-audit`, `market-grid`, `compare-grid`, `goal-robustness`, `compare-robustness`, `builder-grid`, `compare-builder`, `small-market-review`, `calibrate`, `validate`, `backtest`, `audit-regressions`, `research`, `fit-goal-model`, `p0-upgrade-benchmark`, `diagnose-p0`, `stake-snapshot`, `recover`, `compare`, `activate`, `sync-supabase`, `postmortem`, `execution`, `approve-policy` |

Исходные 52 команды сохраняют синтаксис и поведение; обычная справка их
не рекламирует. Явный вызов hidden-команды допустим для совместимости.
`--labs` меняет справку, не permissions. Защиту monetary path по-прежнему
обеспечивают contracts, seal, policy, calibration/holdout и Money Gate.
Физической изоляции всех LABS первый этап не обещает.

| Вход | Статус |
|---|---|
| `sefirot.py`, установленный console script `sefirot` | KEEP_STABLE: один `sefirot.cli.main` |
| `run_sefirot.py`, `SEFIROT_CORE.py` | DEPRECATE: canonical wrappers по умолчанию; прежний интерфейс только `--legacy` |
| `scripts/capture_snapshot.py` | DEPRECATE: legacy инструмент, сохраняется до отдельной миграции |

## 4. Lean architecture без новой модели

| Слой | Текущий ответственный код | Выход |
|---|---|---|
| data | gateway/provider + archive + data-session/forward | API receipts, вся заранее назначенная выборка, missing facts |
| forecast | evidence + probability + engine.prepare + Service.capture | Price-blind baseline и immutable seal |
| calibration | probability + Service/calibration_history | Raw/base и статус bins; неизвестная calibration не становится GREEN |
| market | odds_provider после seal | Exact event, полная линия, receipt; Stake отдельно в LABS |
| decision | engine.decide + risk + decision_card | EV/stress, причины PASS, класс, stake |
| evaluation | forward.settle_plan + forward_scorecard | Original probabilities, результаты API, полный знаменатель, metrics |

Daily workflow: `data-session` → seals/coverage → `readiness` →
`fetch-odds` → `decide` → `forward-settle` → `forward-scorecard`.
`capture` оставлен для интеграций с уже полученным sports JSON. Forecast
не читает цены. RESULT JSON без API receipt в compatibility-команде `result`
не заменяет API evidence для forward-scorecard.

Первый этап не объединяет все эти команды в новый orchestration engine:
существующий data-session остаётся единственным ежедневным sports collector.
На недостаточной истории выход — PASS с сохранённой попыткой и coverage.

## 5. Migration plan

1. Зафиксировать карту и этот проект решения отдельным коммитом до кода.
2. В следующем малом коммите: curated help, build-info без БД/сети,
   canonical wrappers, optional research grids, актуальные инструкции.
3. Пройти существующий release gate и контрпримеры: default collector не
   импортирует grids; explicit LABS сохраняет их; отказ grids не уничтожает
   seal; wrappers совпадают с canonical; help/identity не создают БД.
4. Опубликовать отдельную feature-ветку и draft PR. Main не сливать.
5. Следующий этап: прочитать реальные original receipts и проверить
   доступность истории/рынка в настроенной среде, затем full prospective cohort.
6. Только после данных — реализовать один challenger по протоколу ниже;
   физическое разделение больших модулей отдельными проверяемыми коммитами.

Широкий перенос пакетов, удаление старых интерфейсов и замена baseline
не входят в первый шаг. Исторические seals/approvals/fits не пересчитываются.
После изменения CLI code_hash изменится; старые decision/replay остаются
на архивной сборке. Model hash и Policy сохраняются.

## 6. Accuracy protocol: проект, до выполнения

**Статус PROPOSED / NOT RUN.** Это точный план будущего эксперимента,
а не уже полученные метрики или автоматическая promotion policy.
Если нельзя собрать указанные API-данные, эксперимент получает
INSUFFICIENT_DATA; ручной веб-анализ или вымышленные данные его не заменяют.

Baseline A: BASELINE_V1/STRICT из source commit выше, model_hash
`46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`,
default Policy, original raw score mass и оригинальные raw/base projections.
Просмотренный historical TEST не используется для выбора challenger/thresholds.

Challenger B: ровно один Dixon–Coles low-score correction поверх **тех же**
price-blind baseline λ. Исправляются четыре клетки 0:0/0:1/1:0/1:1,
затем проверяется положительность и нормировка. Один rho выбирается
на TRAIN из сетки −0.15…+0.15 с шагом 0.005 по goal log loss.
При равенстве — rho с меньшим модулем, затем меньший rho.
Неустранимая неположительная масса на новом матче означает PASS.
Новые roster, neutral-venue, tempo, market и count features не добавляются.

Feature schema: зафиксированные match/team/league/profile IDs, regulation
FT goals, venue home/away, kickoff/finished/received times и разрешённая
baseline история. Никаких odds/market-implied probabilities или будущих
результатов в sporting features. Нейтральная площадка не подтверждена
baseline: такие матчи заранее исключаются из основного сравнения и
остаются в coverage. Unknown venue не выдаётся за подтверждённый home.

Предлагаемые границы, фиксируемые **до** получения TUNE/HOLDOUT labels:

| Split | Kickoff по Europe/Kyiv | Использование |
|---|---|---|
| TRAIN | [2024-07-01, 2026-10-06) | Fit rho, chronological sports reconstruction; пометка historical |
| TUNE | [2026-10-06, 2026-12-01) | Одна проверка корректности; без выбора второго challenger; probability bins fit только здесь |
| HOLDOUT | [2026-12-01, 2027-03-01) | Новая заранее назначенная API-выборка; ни fit, ни refit |

Список лиг/profile и source coverage должен быть подписан отдельным
dataset manifest до старта TUNE; сейчас он **не разрешён и не заполнен**,
поэтому протокол не запущен. Включаются все будущие NS в объявленных
лигах, не только удобные результаты. Один fixture — одна независимая
единица; 7 рынков одного матча не считаются 7 матчами.
Минимум HOLDOUT: 300 paired eligible fixtures и paired coverage ≥80%
от заранее назначенного eligible cohort. Недостаток — INCONCLUSIVE,
без переноса границ после просмотра результатов.

Метрики original raw и base показываются раздельно: 1X2 multiclass
log loss/Brier, reliability bins (10 фиксированных интервалов), ECE,
exact-score log loss; 1X2 accuracy только вспомогательная. Бины без
наблюдений — null. Goals, markets и layers не смешиваются в одно число.
Market benchmark — отдельный post-seal объект и paired cohort; при
отсутствующей полной API-линии он остаётся null.

Предложенный promotion gate: верхняя граница 95% CI среднего paired
Δ(challenger−baseline) exact-score log loss <0; для 1X2 log loss и Brier
верхняя граница ≤0; ECE не хуже более чем на 0.01. CI — 10,000 bootstrap
ресэмплов целых игровых дат, фиксированный seed 2501. Нельзя ресэмплировать
рынки как независимые матчи. Провал gate или N/coverage — baseline остаётся.
Одна проверка HOLDOUT; после просмотра набор считается consumed.

False-strong — отдельная диагностическая оценка calibration класса A,
не доля проигравших ставок. По полным A WIN/PUSH/LOSS predictions в
фиксированных contract/profile/reliability bins считаются эмпирические
частоты и разница с mean predicted probability; без ≥50 наблюдений в
бине вывод null/INSUFFICIENT. Пока реальных A admissions нет, false-strong
rate null. Один проигрыш класса A не считается доказательством miscalibration.

Default модель даже после успешного исследовательского сравнения меняется
только отдельным review/release, с новым unseen денежным HOLDOUT и прежними
policy/constitution ограничениями. Этот этап не выпускает «2.5-RC1 готов».
