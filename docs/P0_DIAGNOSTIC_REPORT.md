# P0 — диагностика исходного benchmark

**EXPLORATORY; денежного допуска нет. Правила исходного TEST не менялись.**

Восстановлено 312 ставок; PnL -30.27; yield -9.70%; mean EV 16.64%.
Модель ожидала 117.76 побед, получено 96. Raw CLV mean 0.014929829607699445, median 0.0; positive fraction 0.4775641025641026.

## 1. Слабая модель?

Парные ошибки на одинаковом subset. Положительная delta означает, что Davidson хуже. Bootstrap: 14 календарных дней, 2000 повторов в полном прогоне. Интервалы условны; сегменты exploratory.

| Сравнение | Δ Brier | Δ LogLoss | 95% Brier interval | 95% LogLoss interval |
|---|---:|---:|---|---|
| Davidson − elo | 0.001677 | 0.000687 | -0.006769…0.008647 | -0.030167…0.027556 |
| Davidson − market | 0.010096 | 0.030357 | 0.003572…0.015847 | 0.009147…0.050390 |

## 2. Нестабильный devig?

Cash EV не зависит от devig: те же исходные ставки. Диагностические группы divergence не являются новой стратегией.

| Метод | N | Market Brier | Market LogLoss | Closing-implied PnL |
|---|---:|---:|---:|---:|
| proportional | 380 | 0.289449 | 0.970552 | -11.94 |
| power | 380 | 0.289756 | 0.971026 | -18.68 |
| shin | 380 | 0.289602 | 0.970635 | -15.85 |

Jaccard при divergence ≥2 pp: {"proportional/power": 0.964516129032258, "proportional/shin": 0.980327868852459, "power/shin": 0.9838709677419355}

## 3. Плохой EV threshold?

Проверяется достоверность заявленного EV, не выбирается новый порог. Положительный исход отдельных bins не разрешает торговать ими.

| EV bin (0=2–4%, 1=4–8%, 2=8–15%, 3=15%+) | N | Mean EV | PnL | Yield |
|---|---:|---:|---:|---:|
| 0 | 33 | 2.97% | 5.69 | 17.24% |
| 1 | 72 | 5.91% | 6.08 | 8.44% |
| 2 | 81 | 10.99% | -1.20 | -1.48% |
| 3 | 126 | 29.98% | -40.84 | -32.41% |

## 4. Плохие cohorts?

Разрезы пересекаются: нельзя складывать их убытки. Отбор плохих групп после просмотра не даёт права вводить production veto.

| Разрез | Группа | N | PnL | Yield |
|---|---|---:|---:|---:|
| selection | A | 13 | -1.75 | -13.46% |
| selection | D | 121 | 0.92 | 0.76% |
| selection | H | 178 | -29.44 | -16.54% |
| promotion | any_promoted | 89 | -28.86 | -32.43% |
| promotion | both_established | 223 | -1.41 | -0.63% |
| season_phase | early | 109 | -38.18 | -35.03% |
| season_phase | late | 94 | -0.84 | -0.89% |
| season_phase | middle | 109 | 8.75 | 8.03% |
| odds_bin | 0 | 12 | -1.07 | -8.92% |
| odds_bin | 1 | 21 | 1.89 | 9.00% |
| odds_bin | 2 | 34 | -4.29 | -12.62% |
| odds_bin | 3 | 62 | 0.63 | 1.02% |
| odds_bin | 4 | 183 | -27.43 | -14.99% |
| side_strength | moderate | 42 | -1.32 | -3.14% |
| side_strength | near_even | 78 | -2.12 | -2.72% |
| side_strength | strong | 19 | -0.40 | -2.11% |
| side_strength | underdog | 173 | -26.43 | -15.28% |
| divergence_bin | 1 | 13 | 15.95 | 122.69% |
| divergence_bin | 2 | 127 | 2.52 | 1.98% |
| divergence_bin | 3 | 127 | -24.47 | -19.27% |
| divergence_bin | 4 | 45 | -24.27 | -53.93% |

## 5. Калибровка и uncertainty?

- davidson: macro ECE=0.062867; mean confidence=0.548494.
- elo: macro ECE=0.053119; mean confidence=0.539258.
- market: macro ECE=0.041606; mean confidence=0.544124.

ECE зависит от размера bins. Все classwise reliability bins опубликованы в JSON. Temperature=1 не исправила исходные прогнозы. Истинная индивидуальная P неизвестна: coverage=null. Wilson и ±15% rate stress другой CORE-модели не приписываются Davidson.

## 6. Смесь причин и CLV

Точное разложение: фактический PnL = модельное ожидание + расхождение closing с моделью + остаток исходов относительно closing. Это бухгалтерское тождество, не доказанная причинная декомпозиция.

| Devig | Model expectation | Closing − model | Outcome − closing | Actual |
|---|---:|---:|---:|---:|
| proportional | 51.90 | -63.84 | -18.33 | -30.27 |
| power | 51.90 | -70.58 | -11.59 | -30.27 |
| shin | 51.90 | -67.75 | -14.42 | -30.27 |

Условный Monte Carlo (независимость матчей):
- p_model: N=312, доля симуляций не выше фактического PnL=0.003; expected PnL=51.9035822539888.
- p_close: N=312, доля симуляций не выше фактического PnL=0.2714; expected PnL=-11.93716646724385.

Closing-implied EV уже учитывает маржу через q_close и не равен raw odds CLV. Положительный mean raw CLV сам по себе не доказывает положительного EV. Execution timestamps отсутствуют: невозможно доказать доступность цены или точно выделить потери исполнения.

## Decay, regression и следующий эксперимент

Сохранены все 54 прежних TUNE trials Davidson; отдельная 3×3 чувствительность goals-модели использует только TRAIN/TUNE. Текущие defaults не объявляются обученными и не меняются. JSON содержит все результаты, а не только победителя.

Рекомендуемая ветка P1 после рассмотрения отчёта: сохранить Davidson baseline и проверить xG/xGA challenger с отдельными данными и новым независимым периодом. Наблюдаемые promoted/early-season ошибки задают гипотезы priors/context; отключение этих групп на просмотренном TEST не является улучшением, подтверждённым вне выборки. Новый P1 здесь не реализован.

## Воспроизводимость и ограничения

Dataset hash: `9d2cf06f9998ee96eaaf76777b4d5d709607a552cf351d3b04d79dc022140922`
Code hash: `2c0df329a3d34cc9894640777a0390dc978cbdce145426deabff7b8244882bbe`
Config hash: `203101533973612d4066e7798b2319e2bf152e8e07a0c7318620c85a1863a4a8`
Design hash: `ecb2449a1786e5b17b0ddae430b54b6bdda5ce11878c46d7a5e3e557abe8afb1`

- P0_DEVIG_SENSITIVITY: run_id `50e16b8de5b23f92d376ba77802c02c6c7efa7fa58bce2224cb9c95ad81842ba`
- P0_COHORT_ANALYSIS: run_id `df61dacc1ac9aa092bdb077e22713130367c9db9829b36aaac14485674adcb1e`
- P0_DAVIDSON_VS_ELO: run_id `1cd6a3106f62510836cc3cf31d85ee228fa3d0fad72cc193e67e3bd13163da5f`

- Historical timestamps unknown; not prospective validation
- All 2024/25 is now seen; no retuning
- Avg is a market reference, not an executable price
- B365 historical quotes do not establish execution feasibility
- Cohorts exploratory; no automatic freeze
- True individual probability coverage not identifiable
- Exact rounds unavailable; early-six uses previous games proxy
- Bootstrap and Monte Carlo rely on dependence assumptions

Shin numerical reference: https://github.com/mberk/shin ; methodology: https://www.sciencepg.com/article/10.11648/10026106 .
Исходные CSV перечислены с SHA256 в каждом JSON и DATA_MANIFEST.json. Команда: см. README и P0_EXPERIMENT_DESIGN.md.
