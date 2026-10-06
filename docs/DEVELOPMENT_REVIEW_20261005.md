# Сефирот: сравнительный обзор и последовательность улучшений

Дата: 05.10.2026. Основа: актуальная feature/data-session-audit-20261004,
CORE 2.4.2, новый Builder-аудит и all-versions аудит. Самопроверка автора
изменений, не независимое внешнее заключение. Сравнение по официальной
документации открытых инструментов; общей проверенной доходности систем
на одной выборке нет, поэтому рейтинг «кто прибыльнее» не присваивается.

## Подтверждённые слабые места

| Область | Что уже есть | Недостаток | Приоритет |
|---|---|---|---|
| Данные | API adapter, immutable archive, cutoff и exact IDs | В последнем сохранённом плане 17 INSUFFICIENT_HISTORY, 0 seals/results; ещё нет usable prospective выборки | P0 |
| Рыночный ориентир | API main quotes, complete-line de-vig, CLV; историческая research диагностика | Денежный holdout использует слабый neutral baseline; superiority к профессиональной линии не доказана | P0 |
| Голы | Прозрачный Poisson, prior/decay, fitted SoS challenger и отдельный benchmark | Default голы независимы, нет fitted low-score dependence, явного neutral venue и learned roster/context effects | P1 |
| Калибровка | Frozen contract/profile bins, holdout gates | При малой базе bins пусты; Wilson/rate sensitivity не являются интервалом истинной P конкретного матча | P0 |
| Сценарий | Sports facts, raw goal thresholds, terminal score branches и history/rate stress | Нет обученных вероятностей первого гола, темпа и conditional goals/shots/corners процесса | P1 |
| Builder | 14 frozen AND goal contracts, redundancy/PUSH checks | Нет joint calibration и API combined-price ingestion; одиночный выигрыш не доказывает Builder edge | P1 |
| Малые рынки | API count coverage, long/recent shrink, venue/outlier/opponent diagnostics | Нет calibrated line-count distributions, joint model или price contract | P1 |
| Эксплуатация | CLI, read-only session/readiness, audit, replay, cloud mirror | Много отдельных команд; нет одного завершённого ежедневного API workflow с валидными фактами и линиями | P0 |
| Provenance | Локальные hash-chain и immutable rows | Нет доказанного внешнего timestamp/witness; local receipt не подпись поставщика, reliability — assertion | P2 |

409 тестов предыдущей сборки проверяли техническое поведение. Большое
число тестов не равно проверенной доходности или улучшению вероятностей.
Исследовательский исторический TEST уже просмотрен — доработки нельзя
подбирать по его итогам. Система остаётся исследовательской; BASELINE_V1/
STRICT и денежные ограничения не меняются этим обзором.

## Сравнение с открытыми инструментами

| Инструмент | Подтверждённая возможность | Полезная идея для Сефирота | Зависимость |
|---|---|---|---|
| penaltyblog | Единый fit/predict интерфейс Poisson, Dixon–Coles, bivariate, negative binomial, Bayesian и других goal models; neutral venue и score grid | Сравнивать baseline и один challenger на одной frozen chronological выборке | Достаточная API-история; модель выбирается на TRAIN/TUNE, затем новый HOLDOUT |
| socceraction | SPADL event streams и xT/VAEP/Atomic-VAEP для оценки действий/состояний | Строить tactical features на прошлых игровых действиях вместо словесной надбавки к λ | Координаты и последовательности событий, которых totals statistics недостаточно |
| flumine | Отдельные validation/exposure controls до исполнения, logging controls | Явные стадии, reject reasons, idempotence и полноценный журнал workflow | Переносить структуру проверок; execution/in-play не подключается |

Это разные компоненты спортивной аналитики. Их функциональные возможности
не доказывают, что они прибыльнее Сефирота или что импорт библиотеки
улучшит текущие прогнозы. Ни одна библиотека не устраняет отсутствующие
данные, неверный контракт, outcome leakage или плохую цену сама по себе.

Официальная документация scikit-learn объясняет, что Brier/log loss
оценивают одновременно reliability и discriminative power; отдельные
reliability bins нужны для понимания поведения вероятностей. Независимые
calibration/validation данные обязательны; random cross-validation для
матчей не заменяет хронологическое разделение.

## Первый небольшой шаг: выполнен

Добавлен `forward-scorecard`, см. [FORWARD_SCORECARD.md](FORWARD_SCORECARD.md).
Он оценивает каждый заранее назначенный матч, сохраняет пропуски в
знаменателе и считает метрики raw/base по отдельным контрактам/лигам/
профилям. Используются исходные seals и связанные forward API result jobs.
Простые neutral и frozen-input climatology ориентиры отмечены как слабые;
отсутствующее сравнение с БК остаётся null. Никакого fitting или certification.

Причина выбора: прежде чем добавлять модель, нужно иметь повторяемый
способ выяснить, стала ли она лучше на полной заранее заданной выборке.
Первый отчёт старого реального плана показывает пробел данных: 0/17
оценённых матчей. Улучшения scoring-инструмента не выдаются за рост доходности.

## Следующие шаги по одному

1. **Сквозная data session.** Проверить доступные через подключённые API
   лиги/сезоны/факты/рынки, объединить их в один план сбора и отслеживать
   отсутствие данных. При недоступном тарифе/источнике сохранять пропуск;
   переход на платный тариф требует отдельного решения владельца.
2. **API market benchmark.** Заранее связать complete bookmaker line и
   receipt с frozen prediction, затем сравнить log loss/Brier на одной
   парной выборке. Closing price — только постматчевый ориентир, не вход
   в sporting forecast; фиктивных historical receipt timestamps не делать.
3. **Один goal challenger.** Начать с Dixon–Coles/neutral-venue или
   bivariate модели; параметры учить на TRAIN/TUNE и freeze до следующей
   выборки. Не переключать default по одной красивой истории/удачному дню.
4. **Один малый рынок.** После данных сначала shots или corners с
   overdispersion/shrinkage и opponent/venue context. Только после отдельной
   проверки line probabilities переходить к goals + count joint model.
5. **Удобный интерфейс.** Одна карточка: data gaps → scenario → probabilities
   → API price → EV/stress → лучший простой рынок → итог/причина пропуска.
   Любой недостаток данных должен быть понятен до запроса коэффициентов.

Карточки — позже, строго через подтверждённого судью, YC/game, YC/foul,
низкий риск 0–1 и правила расчёта. Фолы не заменяют ЖК. LIVE/догон,
автоматическое размещение и дополнительные агенты не добавлены.

## Источники, просмотренные 05.10.2026

- https://penaltyblog.readthedocs.io/en/latest/models/overview.html
- https://socceraction.readthedocs.io/en/latest/documentation/valuing_actions/index.html
- https://betcode-org.github.io/flumine/controls/
- https://scikit-learn.org/stable/modules/calibration.html

Источники подтверждают возможности инструментов и методологию; вывод о
приоритетах Сефирота — наша оценка текущего кода и данных. Веб не использовался
для анализа конкретных матчей или ручной подстановки коэффициентов.
