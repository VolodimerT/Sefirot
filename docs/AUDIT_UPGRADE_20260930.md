# CORE 2.3 — ответ на аудиты 27–30 сентября 2026

Прочитаны полностью Foundation v0.1 и четыре новых документа: SEFIROT_POSTMATCH_AUDIT_2026-09-27.md, SEFIROT_POSTMATCH_AUDIT_2026-09-28.md, SEFIROT_DAILY_AUDIT_2026-09-29.md, SEFIROT_AUDIT_2026-09-30_AND_UPGRADE_PLAN.md. Их SHA256 сохранены в examples/audit_cases_20260927_30.json. Исходные документы содержат личный финансовый журнал и в публичный Git не копируются.

Это обновление механизмов контроля и диагностики. Улучшение прогнозного качества CORE 2.3 **не установлено**. Ранее отрицательный реальный benchmark не переобучался; уже просмотренные результаты не превращены в новый тест.

## Реализация требований

| Требование | Статус и реализация | Что остаётся |
|---|---|---|
| P0.1 Competition profiles | Реализована изоляция истории, calibration bins, компетенции, рейтингов, парных сравнений и отчётов по MEN/WOMEN/RESERVE/LOWER/UNKNOWN | Отдельных fitted priors, tail и player coefficients нет; классификация популяции/уровня требует решения |
| P0.2 Strength-of-schedule | Диагностический opponent attack/defense и bounded weight для каждого подходящего исторического матча, frozen at kickoff, без поздних результатов | Вес не меняет lambda; полноценная модель SoS не обучена. История ограничена текущим окном history_days, поэтому trace не равен архиву рейтингов лиги |
| P0.3 Graded death-test | ROBUST_VALUE / FRAGILE_VALUE / AGGRESSIVE_VALUE / NO_VALUE, base/stress min/max, отчёты по классам | Пороги предварительные; снятие блока stress<0 и новые stake caps **не реализованы** без отдельного невиденного теста. Это явное незакрытое требование |
| P0.4 Threshold probability | P(0), P(1), P(2+), P(3+) из согласованного распределения счёта | Это проекции прежнего Poisson, а не новая обученная threshold-модель |
| P0.5 Divergence gate | Полная линия одного БК без маржи; условная вероятность при no PUSH; одиночная цена labelled proxy. Extreme divergence требует independent sports recalculation и блокирует общий допуск | Sharp consensus нескольких БК отсутствует. Пороги 0.10/0.20 исследовательские |
| P0.6 Settlement/audit | Вектор prediction error, Brier, raw/base/Low/High, base/stress EV, reasons, factual premises, WIN/PUSH/LOSS, UNKNOWN premise review, CLV зарегистрированного исполнения отдельно от quote CLV | Closing и entry появляются только при наличии записи; достоверность предпосылок требует доказательств, не вывода из счёта |
| P1.1 Overdispersion | Оставлено открытым | Negative Binomial/mixture не обучены и не сертифицированы; имя goals-gamma-v1 не означает NB predictive distribution |
| P1.2 Home/away splits | Оставлено открытым; прежняя модель использует общую историю команды и home prior | Раздельные fitted attack/defense ещё не реализованы |
| P1.3 H2H | Контракт matchup INFERENCE и конфликт → UNKNOWN/RECALCULATE | Автоматический численный contextual modifier не реализован |
| P1.4 Player impact/GK | Составы и травмы обязательны; можно доказательно оценить предпосылку после матча | Численные эффекты GK/CB/DM/scorer/creator не обучены |
| P1.5 CLV | Одни правила/рынок/БК; CLV quote и зарегистрированного исполнения раздельны | Наличие цены и provenance пока заявлены поставщиком; для аудитных случаев closing отсутствует |
| P1.6 Exposure | Действующие caps матча/лиги/команды/сценария/модели плюс presealed thesis guard для связанных рынков | Двойники/экспрессы остаются D1, количественная корреляция не выдумывается |
| Каталог причин | 10 новых категорий плюс UNKNOWN; ссылки на доказательства и HELD/FAILED/UNKNOWN для конкретных предпосылок | Ссылки проверяются на наличие, не на содержание; причинный вердикт проверяющего может быть ошибочным |
| Новые примеры | 49 сообщённых случаев; точные целые линии/PUSH, явно unsupported четвертные линии, builder и малые рынки | Нет исходных seal/источников/closing; нет реконструкции истинного prematch-прогноза |

## Зафиксированные противоречия

1. Аудит 30 сентября категорично называет Belgrano MODEL_MISS и Taunton BAD_PASS_FALSE_NEGATIVE. Аудиты 27–29 сентября и Foundation P9/P13 говорят, что WIN не доказывает value или ошибочность PASS. Эти категории принимаются как гипотезы проверяющего; автоматическое качество UNDETERMINED. Ни один выигравший случай не служит причиной обучить/одобрить новый фильтр.
2. Предлагается сразу заменить stress<0 BLOCK уменьшенной ставкой, но тот же аудит требует holdout точных порогов. Диагностическая градация готова; новый monetary policy остаётся OPEN. Старый veto сохранён, что прямо отличается от желаемых денежных regression outcomes Tamworth/Taunton.
3. MEN/WOMEN описывают популяцию, LOWER — уровень, RESERVE — состав турнира. Они пересекаются. В этой версии enum — явный первичный профиль, UNKNOWN при неоднозначности; переход к двум осям требует нового контракта и проверки, не молчаливой классификации.
4. N2 запрещает трактовать движение как доказательство; новый THESIS_REPLACEMENT_GUARD использует движение только для временного запроса проверки предпосылок. Он не обнуляет вероятность и не доказывает ложность тезиса.
5. «Предпочтение protected line при близком EV» требует заранее определённого критерия близости и контроля пула. Расчёт PUSH уже точен; новый price-driven перебор линий не добавлен. Заранее объявленный пул сохраняется.

## Проверка Конституции

| Правило | Контроль после обновления |
|---|---|
| F1 независимая вероятность раньше цены | prepare не принимает quotes; пороги/SoS сохраняются до цены; market_reference после seal; смена odds не меняет probability |
| F2 EV не даёт автоматического допуска | stress label не permission; все gates, holdout, компетенция, policy approval, свежесть и риск сохраняются |
| F3 только невиденные данные | 49 известных случаев помечены unverified/retrospective/holdout=false; CLI не создаёт predictions. Новое decide после kickoff запрещено даже с backdated at |
| F4 деградация/восстановление | Старые WEAK/FROZEN/recovery действуют в контексте профиля; новая версия не наследует чужую сертификацию |
| F5 воспроизводимость | Версия 2.3.0, policy v2, code/policy/input hashes, исходные признаки/котировки/причины и captured context; replay требует архивной версии кода |
| F6 UNKNOWN | Неизвестный профиль, matchup conflict, novelty, extreme divergence и unexplained movement не получают обычное доверие |
| F7 FACT/INFERENCE/ASSUMPTION | Matchup только INFERENCE с надёжными FACT supports; SoS/status/grades явно исследовательские; отсутствие данных не заполнено задним числом |
| F8 критический veto выше рейтинга | Новый divergence/thesis/profile block не отменяется HIGH trust, ROBUST grade или большим EV; Арбитр не усредняет veto |

Проверены P1–P16/N1/N2: закрытый pool ≤7, один исход на семейство, sport-first scenario, обязательные sports recheck/revision, evidence chronology, отдельные качество/результат, причины UNKNOWN, мониторинг и контекстный рейтинг, консервативные caps без догона, version comparison, allowed override reasons. Снятие stress veto, автоматический H2H, trained profile model и sharp consensus прямо отмечены OPEN. D1/D2 остаются незавершёнными; LIVE отсутствует.

## Владелец функций и поток

Список девяти сефир не меняется. Свидетель проверяет профиль/FACT supports; Сценарий хранит thesis_links; Вероятность выдаёт score mass/thresholds/SoS diagnostics; Компетенция изолирует рейтинг и калибровку; Рынок выдаёт quote/no-vig/EV; Оппонент запрашивает пересчёт по conflict/divergence/thesis/stress; Арбитр допускает только после всех veto; Летописец хранит settlement/error/review/CLV. Порог проверяет формат и prematch-окно. Новые функции не стали агентами.

Новый фрагмент потока: declared profile → sports-only seal с threshold/SoS/thesis → полный recheck → bookmaker reference/EV/stress class → conflict или thesis guard → новая sports-only ревизия в пределах max_revisions либо PASS → допуск → риск → запись → результат → error/Brier/автоматический UNDETERMINED → доказательный review → профильная компетенция. Изменение цены само не запускает fit и не делает пересчёт вероятность под линию.

## Самопроверка архитектуры

- Дублирование ограничено: единый grade_stress для live-independent prematch/report/retrospective; единый settle; нет второй вероятности у Оппонента. Прежний пакет совместимости ещё присутствует, основной запуск sefirot.py.
- Арбитр не получил права менять sports seal. Летописец не может автоматически назвать выигравший PASS ошибкой. Человек с доступом к коду всё ещё может сфальсифицировать данные/часы.
- Рекалькуляция — новая immutable ревизия с пределом попыток, не цикл двух агентов. Вечный конфликт завершается PASS; автоматического поиска нового достоверного источника пока нет.
- Ни рейтинг, ни diagnostic ROBUST не компенсируют нехватку калибровки или факт-конфликт. Cohort win rate не используется для одобрения.
- Исторический opponent context исключает self/future/late receipts. Текущая ограниченная история снижает полноту SoS; она не должна выдаваться за точный исторический рейтинг.
- Эти 49 исходов уже просмотрены: на них можно ловить технические дефекты, нельзя выбирать лучшие пороги и объявлять эффективность. Итоговый независимый тест должен быть новым.
- False confidence остаётся возможной из-за Poisson, общих priors, малого bins sample, single-price proxy и ложного human evidence. Все эти ограничения сохраняются в отчёте.

## Воспроизведение

```powershell
py -3 test_sefirot.py
py -3 sefirot.py demo
py -3 sefirot.py audit-regressions examples/audit_cases_20260927_30.json
py -3 scripts/verify_release.py
```

Числа фактического прогона: reports/TEST_REPORT.md, TEST_OUTPUT.txt, RELEASE_CHECK.json, AUDIT_REGRESSION_REPORT.json. Внешний независимый аудитор не привлекался: проведена самопроверка, а не выдано чужое заключение. Новая версия не объявляется полностью реализовавшей все эмпирические требования аудита.
