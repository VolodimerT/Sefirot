# Соответствие SEFIROT CORE 2.0 исходному аудиту

Дата: 2026-09-26. «Реализован» означает исполняемый программный механизм с тестом, **не подтверждённую прибыльность или достоверность входного провайдера**. Исходная Конституция F1–F8 не изменена. Внешнего независимого эмпирического аудита ещё нет.

| Правило | Реализация | Проверка / граница |
|---|---|---|
| F1 Независимая вероятность | `capture`, строгий sports-only контракт, seal раньше quotes; расхождение требует независимых источников | `test_F1_*`, `test_divergence_*`; модель не использует линию |
| F2 Финальный допуск | `engine.decide`: все veto → holdout/компетенция/политика/recheck → риск → BET/PASS | `AdmissionTests`; реальные допуски пока не подтверждены данными |
| F3 Невиденный тест | `reserve`, frozen calibrator, holdout ID/время, capture timestamp, запрет future/target leakage | `test_F3_*`, `CalibrationFlowTests`; локальные часы не нотариальное доказательство |
| F4 Деградация | `competence`, WEAK/FROZEN, сохранённая заморозка, `recover` после новых прогнозов/исправления/validation | `test_degradation_*`, `test_recovery_*`; статистические пороги экспериментальные |
| F5 Воспроизводимость | Полный payload спортивных входов, модели, политики, котировок, контекста и портфеля; hash-code; replay | `test_F5_*`, tampered payload; старому решению нужна архивная версия кода |
| F6 Неизвестный режим | Мало истории, novelty/coach/rotation, неизвестная компетенция и необъяснённая линия | `test_F6_*`, empty history; новости должны поступить от поставщика |
| F7 Виды доказательств | FACT/INFERENCE/ASSUMPTION, фактологические ссылки без циклов, критические предположения блокируют | `test_F7_*`; тип записи не доказывает её правдивость |
| F8 Критический ограничитель | Нет среднего голосования; отдельные veto и limiting_factors | `test_each_critical_veto_*`, `test_critical_errors_*` |
| P1 Первичный отбор | Проверка формата, времени, идентичности, истории | integration/negative tests |
| P2 Сценарий до рынка | `prepare` фиксирует scenario и bounded pool до цены | price-independence tests |
| P3 Основание вероятности | История лиги/команд, давность, состав/контекст как gates, frozen calibration, диапазон и чувствительность | math/calibration tests; тактические коэффициенты не обучены |
| P4 Конфликты | Явные противоречия, supersedes своего источника, новая ревизия, предел пересчётов | `test_P4_*`, P15 tests |
| P5 Death-test | Контрсценарии, слабые предпосылки, границы EV, EV при изменении темпа | ordinary loss branch test; Оппонент не создаёт свою вероятность |
| P6 Качество источников | ID, независимые группы, доверие, observed/published/received, отключённый/старый источник | disabled source/future evidence tests |
| P7 Перепроверка | Полные повторные evidence; изменение спорта → новый seal; freshness по observed_at; OPEN/FINAL/ENTRY/CLOSE | `test_P7_*`; entry отражает запись человека |
| P8 Причины ошибок | Автоматический postmatch report + отдельный доказанный postmortem; UNKNOWN допустим | feedback/postmortem tests |
| P9 Качество отдельно от исхода | WIN/LOSS/PUSH/VOID отдельно от GOOD/WEAK/ERROR/UNDETERMINED | `test_P9_*`, VOID test |
| P10 Компетенция | league / market / scenario / model, n, Brier, baseline, uncertainty, состояния | governance and calibration flow tests |
| P11 Риск | Flat stake с понижающими ограничениями, потолки ставки/матча/дня, просадка, нулевой риск → PASS | risk/drawdown/daily tests; defaults не одобрены для денег |
| P12 Связанная экспозиция | Общие match/team/league/scenario/model/factor, лимит группы, повтор матча блокируется | correlation/execution tests; нет эмпирической корреляционной матрицы |
| P13 Защита от шума | Unique match ratings, minimum samples, confidence, два периода holdout, два окна деградации | paired/calibration/governance tests; множественные сравнения остаются риском |
| P14 Версии и откат | Общее множество кейсов, paired comparison, shadow/promotion/rollback, активный calibrator, архив кода | paired comparison tests; положительная реальная promotion не выполнена |
| P15 Ручное вмешательство | Пять причин, parent/новая revision, immutable original, лимит попыток | `test_P15_*`, unchanged/market-shopping tests |
| P16 Рейтинг сефир | Каждая из 9 ролей: контекст/версия/n/интервал/грубые ошибки; основные роли участвуют в допуске | ratings in report; мало проверок означает INSUFFICIENT, не выдуманный рейтинг |
| N1 Основные рынки | Закрытый пул до цены, максимум 7/по одному на семейство; fewer assumptions, robust stress EV | bounded pool/market shopping; отсутствующие цены не подменяются |
| N2 Движение/closing | OPEN→FINAL изменение, evidence причины, закрывающая линия, CLV одной линии/БК | closing/freshness tests; причина требует исходного факта |
| D1 Экспрессы | Закрыты по исходному аудиту | unsupported market tests |
| D2 Малые рынки | Закрыты по исходному аудиту | unsupported market tests; фолы и карточки не объединены |

## Что не выдаётся за выполненное

- Эмпирическая валидация и прибыльность на реальных невиденных матчах.
- Полностью автоматическая проверка спортивного провайдера и количественная модель тактики/игроков.
- Внешняя защищённая фиксация времени и независимый сторонний аудит.
- Подключённая Supabase/Tavily инфраструктура: текущий автономный продукт использует SQLite и локальный inbox.
- Экспрессы и малые рынки остаются в статусе «на доработку», как требует аудит.
