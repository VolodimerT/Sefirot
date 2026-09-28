# SEFIROT P0 — дизайн диагностики CORE 2.0

Дата: 27.09.2026. Версия дизайна: 0.1. Статус: **УТВЕРЖДЕНО пользователем 27.09.2026**.
Основание: полностью прочитанное SEFIROT_DESIGN_CHAT_TASKS_P0_P2.md; проверенные локальные исходники CORE 2.0 и исходный REAL_DATA_BENCHMARK.json. Основная архитектура не переписывается. Этот документ — проект эксперимента, не результат P0. Новые разрезы TEST ещё не рассчитывались.

## 1. Карта проблемы и подтверждённая исходная точка

В репозитории VolodimerT/Sefirot выпущен CORE 2.0, main на момент постановки — 84f29cc84f54644ca84d3feae06a15c64c1327e0. Перед будущей реализацией проверяется актуальный main, чужие изменения сохраняются.

Исходный benchmark: EPL 2020/21–2024/25, 1900 матчей. TRAIN=760, TUNE=380, CALIBRATE=380, TEST=380. Все пять локальных CSV найдены; SHA256 каждого и нормализованный dataset_hash совпали с исходным отчётом.

| Модель / линия, TEST | Brier (/2) | LogLoss | Macro ECE |
|---|---:|---:|---:|
| Davidson с выбранной температурой | 0.299545 | 1.000909 | 0.062867 |
| Legacy Elo | 0.297868 | 1.000223 | 0.053119 |
| Avg preclose, proportional | 0.289449 | 0.970552 | 0.041606 |

Davidson хуже Elo по Brier на 0.001677 и по LogLoss на 0.000687. Отставание от рыночного baseline больше: 0.010096 и 0.030357. Статистическая устойчивость этих разниц пока не оценена. ECE зависит от разбиения и размера выборки и не заменяет proper scores.

Симуляция: 312 ставок, −30.27 единицы, yield −9.7019%, max drawdown 40.78, средний raw odds CLV +1.493%. Это архивная симуляция на B365, не история фактических исполнений. Нельзя пока приписывать весь проигрыш одной причине.

Код показывает две разные модели: CORE goals model использует decay/shrinkage/stress; исследовательский Davidson использует рейтинги, сезонную регрессию и temperature. Нельзя объяснять убыток Davidson параметром half_life_days другой модели.

## 2. Противоречия задания и предлагаемые решения

**C1 — EV и devig.** Денежный EV = p_model × offered_odds − 1. Devig в эту формулу не входит. При сохранении исходной вероятности, котировок, выбора стороны и порога все три метода обязаны восстановить одни и те же 312 ставок: Jaccard=1, одинаковые PnL/yield/drawdown/raw CLV. Если это не так, эксперимент меняет правила или содержит ошибку.

Предлагается два явно разделённых отчётных слоя:

1. **Frozen cash-EV selection:** исходные 312, одинаковые при всех devig. Это основной ответ на требование «ставки при EV ≥2%».
2. **Market-disagreement diagnostics:** на тех же зафиксированных сторонах рассчитывать Δ=p_model−q_method, признаки Δ>0 и отдельно Δ≥0.02 (2 процентных пункта, не 2% EV). Для этих диагностических множеств показать Jaccard, пересечение, уникальные элементы и их реализованные результаты. Это разбор существующих ставок, не новая стратегия и не ретроспективное разрешение отфильтровать убытки.

При необходимости fair-price ratio p_model/q_method−1 выводится только как отдельная диагностическая величина, не как денежный EV. Новый выбор «лучшей стороны» по devig не производится.

**C2 — туры.** CSV не содержит подтверждённого номера тура. «Первые 6 туров» нельзя незаметно заменить первыми 60 матчами: переносы искажают результат. Пока точный разрез получает NOT_AVAILABLE; дополнительно явно названный proxy — обе команды сыграли <6 матчей текущего сезона до дня матча. Позднее можно добавить отдельный официальный schedule manifest с хешем, не подмешивая его скрытно.

**C3 — интервалы.** Исходный Davidson-run не содержит Low/High; ±15% относится к чувствительности интенсивностей голов другой модели. Coverage индивидуальной истинной P на этих 312 ставках — NOT_IDENTIFIABLE. Нельзя задним числом приписать прогнозам интервалы CORE.

**C4 — критерий «режим отключить».** Сегмент, найденный на уже просмотренном TEST, даёт гипотезу для следующего исследования. Он не даёт права менять production freeze/thresholds. P0 выдаёт кандидатов для проверки, а не автоматические veto.

Все четыре решения требуют утверждения вместе с этим документом; ни одно не считается молча принятым.

## 3. Точный дизайн P0 и ожидаемые результаты

| Шаг | Действие | Результат |
|---|---|---|
| 0 | Заморозить approved design/config, исходный run и хеши | Манифест эксперимента до расчёта новых cohorts |
| 1 | Восстановить predictions и выбор сторон из CSV при старых параметрах | 380 прогнозов и точное соответствие всех 312 ставок |
| 2 | На одном subset рассчитать proportional/power/Shin | Различия baseline, divergence, устойчивость диагностических флагов |
| 3 | Разобрать только исходный портфель по заранее заданным группам | Где сосредоточены убыток, завышенный EV и CLV |
| 4 | Сравнить Davidson/Elo/рынок на одних match IDs | Парные разницы ошибок и интервалы неопределённости |
| 5 | Исследовать существующие decay/regression на TRAIN/TUNE | Карта чувствительности без изменения модели TEST |
| 6 | Проверить трактовку calibration/uncertainty | Измеримые ошибки калибровки и дизайн следующей проверки интервалов |
| 7 | Проверить воспроизводимость, регрессии, Windows/Linux CI | Три JSON, диагностический Markdown, полный журнал проверок |
| 8 | Ответить на шесть вопросов задания и выбрать направление P1 | Количественный вывод с неопределённостью; P1 не запускается автоматически |

Параметры исходного Davidson: k=40, home=120, draw=0.8, season regression=0.8; temperature=1.0. Они остаются неизменными. Legacy воспроизводится ровно существующей функцией с legacy=True и прежними defaults. Все результаты одного календарного дня обновляют рейтинги только после прогнозов на весь день. Более ранние TEST-результаты допустимы для заранее определённого online-update последующих дней; подбор параметров на TEST запрещён.

## 4. Devig и единый subset

Основной market baseline — Avg H/D/A, как в исходном benchmark. B365 — отдельная линия для offered odds и same-book preclose/closing CLV. Не смешивать Avg и B365 в одной серии движения линии.

Для всех трёх методов один intersection-subset полных допустимых Avg 1X2. Из исходных 380 не исключать матчи молча: отчёт хранит included/excluded IDs, причину, coverage. При ошибке Shin нельзя тихо заменить его proportional. Некорректная котировка, NaN/Infinity, odds≤1, неполная линия — явная ошибка/исключение. Underround для Shin в v1 объявляется неподдержанным; такой матч исключается из общего сравнения всех трёх, но сохраняется в исходном портфеле. Нулевая маржа — проверяемая предельная ветка.

Shin: решается одно уравнение нормировки на физически допустимом z∈[0,1), с ограничением числа итераций и проверкой невязки суммы P. Зафиксировать абсолютный tolerance 1e-12 и max_iterations=200; никакой скрытой нормировки результата при существенной невязке. Метод и edge cases проверяются по первичному описанию и независимым эталонам, не только по собственному solver.

Технический источник: Clarke, Kovalchik, Ingram, “Adjusting Bookmaker’s Odds to Allow for Overround” (2017), https://www.sciencepg.com/article/10.11648/10026106 . Реализация для независимых контрольных примеров: https://github.com/mberk/shin (при реализации фиксируется версия/commit).

Для каждого метода: N матчей и ставок, cash-EV метрики, Brier/LogLoss, mean/median/quantiles divergence по всем 3 сторонам и отдельно выбранной стороне. Mean EV — арифметическое среднее исходного cash EV. Raw CLV = O_entry/O_close−1: mean/median/positive fraction и знаменатель доступности. Дополнительно same-method movement q_close−q_entry и closing-implied expected return q_close×O_entry−1. Последний — оценка через closing benchmark, не истинный EV.

Jaccard(A,B)=|A∩B|/|A∪B|; при обеих пустых группах null с причиной EMPTY_UNION, не искусственная единица. Отдельно показать три попарных пересечения, общее пересечение и exactly-one-method группы для каждого диагностического флага.

## 5. Cohort boundaries — предлагается зафиксировать сейчас

Все интервалы слева включены, справа исключены, кроме последнего. Категории не выбираются по исходам. Общий интерфейс market_family поддерживает расширение, но текущий отчёт содержит исключительно 1X2; handicap/total/BTTS/team_total — NOT_IN_DATASET.

| Измерение | Правило |
|---|---|
| Odds | [1,1.50), [1.50,1.80), [1.80,2.20), [2.20,3), [3,∞) |
| Cash EV | [0.02,0.04), [0.04,0.08), [0.08,0.15), [0.15,∞) |
| Selection | home / draw / away |
| Season progress | u=(home_games_before_day+away_games_before_day)/2; early u<13, middle 13≤u<26, late u≥26; early-six proxy отдельно |
| After season change | первая игра сезона хотя бы одной команды (games_before_day=0) |
| Side strength | q_selected proportional Avg: strong ≥0.60, moderate [0.45,0.60), near-even [0.30,0.45), underdog <0.30; это вероятность выбранного исхода, не сила команды |
| Divergence | negative <0; [0,.02), [.02,.05), [.05,.10), [.10,∞); baseline proportional Avg, другие методы отдельными столбцами |
| Promoted | команда TEST-сезона отсутствует в составе EPL предыдущего полного сезона; отдельно any promoted, both established и тип выбранной команды; для draw — N/A выбранной команды |
| Month | YYYY-MM |
| Rolling | каждые последовательные 50 исходных ставок, stride=1, сортировка date затем match_id; крайние неполные окна не создавать |

Состав сезона для promoted — отдельный roster-only manifest: извлекаются имена без результатов, статус known-before-season является реконструированной меткой, а не доказанным историческим receipt. Если предыдущий сезон неполон, promoted=UNKNOWN. Возврат в EPL также считается promoted; не утверждается первый выход в истории клуба.

Группы season phase взаимоисключающие; early-six — дополнительный перекрывающийся тег. Для каждой оси N/PnL/число побед восстанавливают общий портфель; суммы разных осей складывать нельзя. Drawdown считается на хронологической подпоследовательности группы с initial equity=0; это не её аддитивный вклад в общий drawdown. Порядок внутри дня условный — дополнительно daily-aggregated drawdown.

Каждая группа: N, stakes, wins/losses, mean odds, mean P, observed win rate, expected wins, mean EV, PnL, yield, max drawdown, raw CLV mean/median/positive fraction/coverage. N<30 помечается descriptive_small_sample; это ограничение интерпретации, не торговый порог.

## 6. Davidson vs Elo и статистические методы

Все 380 TEST-матчей, и отдельно единый market subset. Сегменты:

- promoted / established; early-six proxy; min(history_count_total)<20 и min(current_season_count)<6 — разные метки;
- top/middle/bottom: preseason legacy rating rank среди 20 команд, места 1–6/7–14/15–20, фиксированные перед первым днём сезона; пары home_band×away_band;
- strong home favourite q_H≥0.60; strong away favourite q_A≥0.60; near-even |q_H−q_A|≤0.10 и max(q_H,q_A)<0.50;
- draw-heavy q_D≥0.28;
- normalized entropy Davidson H(P)/ln(3): low≤0.80, high≥0.95, middle иначе;
- disagreement max_i|P_Davidson,i−q_proportional,i|: low≤0.05, high≥0.10, middle иначе.

Market-based сегменты используются после seal только для диагностики, не как sports features. Рейтинги и counts берутся из trace до обновления результата, не восстанавливаются из итоговой таблицы сезона.

Метрики: Brier=½Σ(p−y)^2; LogLoss с clip=1e-15; N, Davidson/Elo/market и парные delta. Отдельно classwise Brier и signed calibration residual по home/draw/away. Reliability/ECE — 10 заранее фиксированных равных bins, без поиска «удачного» разбиения. Calibration у Davidson — temperature, а не reliability-calibrator CORE.

Неопределённость парных delta и yield: moving-block bootstrap календарных дней, блок 14 дней, 2000 повторов, seed=212200, 95% percentile intervals. Полный календарь включает пустые дни, обрывы сезона не склеиваются. Одни и те же resamples для всех моделей/методов. Нулевой размер группы в replicate даёт null; число валидных replicates публикуется. Условная оценка зависит от предположений о временной зависимости; перекрывающиеся rolling окна не независимы.

Основные сравнения заранее: Davidson−Elo и Davidson−proportional market на полном paired subset. Cohorts exploratory: никаких автоматических выводов «значимо лучше» из десятков срезов и никаких production-исключений по этим результатам. При вводе формальных p-values необходима заранее объявленная коррекция множественных сравнений; в v1 p-values не обязательны.

Полезное точное бухгалтерское разложение, не причинная идентификация:

Σ(O×Y−1) = Σ(O×P_model−1) + Σ[O×(q_close−P_model)] + Σ[O×(Y−q_close)].

Показать три слагаемых для каждого closing devig на одном subset и отдельно недостающий closing. Первое — заявленная прибыль; второе — расхождение модели с closing reference; третье — остаток относительно reference. Последний включает случайность И ошибки closing, а не «чистую variance».

Monte Carlo (10 000, seed=212201) на фиксированных 312 выбранных исходах отдельно под P_model и q_close покажет положение наблюдаемого PnL в условном распределении. Независимость матчей — явное упрощение; MC не доказывает справедливость closing и не идентифицирует точный процент убытка от каждой причины.

Вопрос «плохой threshold 2%?» исследуется через заранее заданные EV bins и observed−expected разницы. Подбор оптимального EV-порога на этом TEST не выполняется. Вывод допустим: «заявленный EV не подтверждается», а не «правильный порог теперь 8%».

## 7. Decay/regression и uncertainty

Документировать без изменений: goals CORE half_life_days=180, prior_games=4, exponential weights, effective sample size, league shrinkage, stress_rate_fraction=.15. Davidson grid уже включал regression=.5/.8.

Чувствительность goals CORE: half-life {90,180,360} × prior {2,4,8}, TRAIN warm-up и TUNE-only оценка chronological goals/1X2 probabilities. Это отдельный диагностический эксперимент другой модели; исторические даты не превращаются в ложные provider timestamps. Не требуется создавать fake CAPTURE ради этой проверки. Для Davidson сначала использовать все 54 сохранённых TUNE trials: сравнить matched regression=.5/.8 при одинаковых k/home/draw. Новая оптимизация или изменение TEST-прогнозов не нужны.

Будущий способ обучения: expanding temporal folds только внутри TRAIN/TUNE, подбор proper-score objective и стабильности по заранее заданным folds; calibration остаётся отдельной, новый untouched/prospective evaluation — отдельным. Ни CALIBRATE, ни TEST не подбирать для decay. Просмотренный 2024/25 навсегда отмечается EXPLORATORY_SEEN для следующего challenger.

Coverage: Wilson интервал относится к частоте в группе при соответствующих предположениях; его попадание на один 0/1 outcome не проверяет индивидуальную P. При наличии отдельного CORE calibrator можно оценить агрегированные held-out bin discrepancies и интервалы частоты, но не называть это coverage истинной P каждого матча. В текущем benchmark такие артефакты отсутствуют: report null + reason.

Предлагаемый следующий uncertainty experiment: временной block-bootstrap sports history/parameter fits с фиксированным числом bootstrap-моделей; сравнить width/stability и proper scores на temporal folds. Для conformal оценивать outcome-set coverage и размер множества на отдельном calibration split; это не Low/High вероятности. Для Bayesian posterior отдельно назвать интервал параметра и predictive распределение исходов, проверить prior sensitivity и misspecification. Выбор метода только после P0; production-реализация сейчас не нужна.

## 8. Data flow и схемы

CSV bytes → SHA256 validation → прежний loader + frozen prediction replay → 380 sealed retrospective P → join preclose/closing → immutable original 312 selection → outcome-blind cohort labels → join outcomes → paired metrics/cohort/CLV/variance → три JSON + Markdown.

Внутри дня labels используют только состояние до дня; outcomes разрешены только в последнем вычислительном этапе оценки и заранее существующих online updates прошлых дней. Closing разрешён исключительно в postmatch metrics. Исходный JSON не переписывается.

Общая оболочка каждого нового JSON:

```text
schema_version, report_kind, status=EXPLORATORY, monetary_permission=false,
source_run_id, source_report_sha256, dataset_hash, source_files[{name,sha256}],
code_hash, design_hash, config_hash, run_id, split, subset_ids, exclusions,
selection_rule, cohort_definitions, seeds, methods, results, limitations
```

Строка матча/ставки:

```text
match_id, date, season, market_family=1X2, selection=H|D|A,
p_davidson[3], p_legacy[3], pre_match_trace,
offered_book=B365, odds[3], closing_odds[3]|null,
market_reference=Avg, q_by_method, ev_cash, selected_original,
cohort_labels, provenance_status, outcome, pnl, clv_raw,
closing_reference_ev_by_method, missing_reasons
```

Dictionaries и массивы имеют канонический порядок. Во всех JSON запрещены NaN/Infinity; undefined metrics — null плюс reason, а не 0. Все числовые сравнения replay: probability/EV/CLV tolerance=1e-12; PnL в единицах tolerance=1e-9; match_id/selection/order должны совпасть точно.

code_hash включает не только research.py/evaluation.py, но весь импортируемый src/sefirot, CLI, diagnostic config/schema. run_id — SHA256 canonical payload без самого run_id и без wall-clock timestamps. Timestamp выполнения — отдельный metadata-файл, не влияющий на детерминизм. Окружение Python/platform/dependency versions сохраняется. Один runtime даёт byte-identical JSON; между платформами допускаются заявленные числовые tolerance, но IDs/selection не меняются. SHA256 не является внешней доверенной печатью времени.

## 9. Карта файлов и CLI

Существующие файлы после утверждения:

| Файл | Изменение |
|---|---|
| src/sefirot/evaluation.py | Дополнительный метод Shin, прежние методы обратно совместимы |
| src/sefirot/research.py | Опциональный pre-match trace без изменения существующих predictions/defaults |
| src/sefirot/cli.py | Команда diagnose-p0 с read-only источниками и exclusive outputs |
| README.md | CLI, пути артефактов, диагностический статус |
| docs/AUDIT_TRACEABILITY.md, docs/FINAL_AUDIT.md | Ссылки и новые ограничения |
| run_sefirot.py, SEFIROT_CORE.py | Deprecated notice без изменения вычислений |

Новые файлы:

- src/sefirot/diagnostics.py — один исследовательский модуль, не новые сефиры;
- config/p0_diagnostic_design.json — утверждённые границы, seeds, tolerances, смысл двух selection layers;
- tests/test_p0_diagnostics.py — математика, replay, chronology, CLI;
- reports/P0_DEVIG_SENSITIVITY.json;
- reports/P0_COHORT_ANALYSIS.json;
- reports/P0_DAVIDSON_VS_ELO.json;
- docs/P0_DIAGNOSTIC_REPORT.md;
- docs/P0_EXPERIMENT_DESIGN.md — утверждённая версия этого проекта.

Планируемая команда (пока НЕ реализована):

```powershell
py -3 sefirot.py diagnose-p0 --csv data/E0_2021.csv data/E0_2122.csv data/E0_2223.csv data/E0_2324.csv data/E0_2425.csv --source-run reports/REAL_DATA_BENCHMARK.json --design config/p0_diagnostic_design.json --output-dir data/p0_run
```

Существующий output не перезаписывается. CLI проверяет hashes, 380 predictions и 312 selections до аналитики; несоответствие — abort с понятной причиной, а не новый baseline. Нет опций retune, optimize-threshold, approve-policy. Доступ к Supabase/Tavily/букмекеру не требуется.

Cleanup secondary: planned removal обоих legacy runners — CORE 3.0, не раньше 01.01.2027; это предлагаемый срок, не обещание выпуска. Старые исторические отчёты не переписываются: в текущих документах помечается их версия и единственный актуальный entrypoint sefirot.py.

## 10. Leakage threat model

| Угроза | Проверка/ограничение |
|---|---|
| Изменённый CSV или source-run | SHA256, dataset hash, сверка IDs и всех frozen bets |
| Результат текущего/будущего дня попал в feature/label | Mutation tests будущих результатов; day batching; pre-match trace |
| Итоговая таблица сезона определяет strength | Только preseason ratings, фиксированный roster; никаких end-season standings |
| Closing подмешан в prediction/selection | Изменение closing не меняет P, исходные ставки, cohorts кроме явно postmatch metric |
| Devig подменил sports probability | p_model hash одинаков во всех методах |
| Cohorts/порог подобраны по убыткам | Утверждённый config hash до нового анализа; TEST diagnostic-only |
| CALIBRATE/TEST влияют на TRAIN/TUNE sensitivity | Физически передавать только TRAIN/TUNE; mutation test последних сезонов |
| Исторические даты выданы за реальные receipt | UNKNOWN_HISTORICAL_TIMESTAMPS, monetary_permission=false |
| Много разрезов породили случайных победителей | Exploratory labels, paired intervals, no auto-freeze, fresh validation |

## 11. Тест-план и acceptance

1. Shin: равные odds, нулевая маржа, обычная положительная маржа, extreme favourite/outsider, перестановочная симметрия, simplex, invalid types/bool/NaN/Infinity, underround policy, nonconvergence; независимые numerical fixtures с provenance.
2. Denominators: все методы используют одинаковые IDs; missing closing не исключает матч из odds-independent forecast scores; CLV coverage явно меньше N при пропуске.
3. Frozen replay: все 380 P и 312 bets, выбранные стороны, EV/PnL/CLV/order совпали. Общие показатели воспроизводятся, а не просто зашиты в assert.
4. Devig invariance: cash-EV selection не меняется при методе; меняются только q/divergence diagnostics; empty Jaccard/null обработан.
5. Cohorts: значения ровно на каждой границе, negative divergence, draw/N/A, unknown promotion, пустые и маленькие группы; сохранение totals для partition-осей.
6. Chronology: будущий результат, price или closing не меняет прошлое P/selection; same-day order не меняет day-level прогнозы.
7. Metrics: hand-calculated PnL/yield/drawdown/CLV, точное трёхчленное разложение PnL, population N; drawdown внутри дня обозначен условным.
8. Bootstrap/MC: одинаковые seeds дают одинаковый результат, paired resamples, пустые группы, нулевая дисперсия, корректные знаменатели.
9. Integration: run twice в разные пустые output dirs → одинаковые canonical JSON/hash/run_id; refusal overwrite; ошибочный hash → nonzero exit без готовых ложных отчётов.
10. Regression: прежние 125 тестов и demo/replay/integrity проходят; новые тесты зелёные на Windows/Linux Python 3.11/3.13. Точное новое число тестов заранее не обещается.

P0 завершён только после всех обязательных артефактов, воспроизводимого CLI, hash/run_id, зелёного CI и количественных ответов на weak model / devig instability / EV threshold / cohorts / calibration / mixture. Не допускается завершение одним советом «нужна новая модель». Невозможный coverage и точные туры помечаются честно, а изменение критерия задания должно быть утверждено.

## 12. Риски, итоговый отчёт и переход к P1

Неидентифицируемые причины не превращать в проценты «виновности». Avg не одна исполнимая цена; B365 CSV не доказанный доступный entry. Raw positive CLV не гарантирует положительный ожидаемый доход из-за маржи, состава выборки, усреднения, ошибок closing и неизвестного исполнения. Отсутствие execution timestamps нельзя исправить статистикой.

312 ставок одного сезона мало для множества устойчивых сегментов. Рыночный baseline не oracle. Bootstrap и Monte Carlo условны, не гарантируют будущую доходность. Нельзя делать вывод по одному N<30 сегменту. Один исторический сезон уже просмотрен и не становится независимым снова после смены названия модели.

Итоговый Markdown должен для каждого из шести вопросов давать: численный эффект; N/subset; интервал/неопределённость; что наблюдается напрямую; что остаётся гипотезой; какой независимый эксперимент проверит её. Также — топ вкладов в PnL и expected/realized gap без скрытого удаления плохих групп.

Только затем выбирать P1: probability weakness → xG challenger рядом с baseline; segment concentration → context hypotheses для новой проверки; devig instability → market robustness; uncertainty failure → новый uncertainty experiment. При смешанной картине Davidson сохраняется baseline. P2 500–1000+ prospective forecasts требует отдельной неизменяемой версии, источников с provenance и нового невиденного периода. На данном этапе P1/P2 не реализуются.

## Решение для утверждения

Утвердить P0 дизайн v0.1, включая C1–C4, фиксированные cohort boundaries и раздельный статус cash EV / market disagreement. После этого реализовать, прогнать, исправить ошибки, дождаться зелёного CI и опубликовать полный P0 отчёт. Основание паузы: раздел задания «КАКОЙ ОТЧЁТ НУЖЕН» прямо требует архитектуру до реализации и её утверждение.
