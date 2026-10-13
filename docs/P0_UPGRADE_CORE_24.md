# CORE 2.4 — P0, исследовательская feature-ветка

База: GitHub `VolodimerT/Sefirot`, CORE 2.3, `96dd95861be6c11bbc450432ca280f9a4d2efd3f`.
Указанный в аудите CORE 2.1 `cf4dca029faf420542d361266d87ac46f0d0d822` — её предок.
Ветка: `feature/p0-sos-threshold-validation`. В main это изменение не слито.

Конституция F1–F8 и P1–P16 не изменена. Девять существующих ответственности остаются в одном процессе. LIVE, догон, дополнительные агенты и размещение ставок не добавлены.

## Что реализовано

| P0 | Поведение | Проверка |
|---|---|---|
| Competition profiles | Fitted artifact принадлежит ровно одной лиге и одному MEN/WOMEN/RESERVE/LOWER. Отдельные priors и count bins; UNKNOWN не заимствует чужую модель | Wrong profile/league, история другого профиля, привязка calibrator/artifact |
| Strength-of-schedule | Голы за корректируются обратной силой защиты соперника; голы против — обратной силой его атаки. Усадка к prior, ограниченные веса, recency. Веса и нормировка фиксируются перед историческим kickoff | Future/self/late receipt, направление весов, неизменность при сдвиге текущего окна |
| Graded death-test | GRADED использует отдельные ROBUST/FRAGILE/AGGRESSIVE, проверку класса на holdout и caps 1/.5/.2. Calibration uncertainty остаётся отдельным veto. Stress ниже −25% блокируется | Условный BET на контролируемых данных; меньшая ставка; общий holdout без class release не допускает; coach/divergence/facts veto |
| Team-total threshold model | Обучаются четыре группы 0/1/2/3+ в заранее заданных rate bands. Dirichlet shrinkage к спортивной базовой модели. Score mass согласована со всеми семью рынками | Сумма вероятностей, точный PUSH, влияние обученных counts, недостаточная выборка и отсутствие стресс-бинов |
| Divergence gate | Полные свежие линии назначенных reference bookmakers дают очищенный consensus. Неполные/старые линии исключаются. Один источник не называется consensus. Extreme divergence продолжает требовать новый sports-only seal | Полная/неполная/старая линия; прежние Roma/Paris-pattern regressions |
| Settlement/audit | Результат автоматически создаёт immutable snapshot. `report` соединяет его с позже поступившими closing, фактическими executions и evidence reviews | Entry ≠ quote, quote CLV и execution CLV, WIN/PUSH/VOID, idempotency и целостность журнала |

SoS использует архив, доступный поставщику, в пределах исторического окна на дату каждого матча. Отсутствующий старый архив не восстанавливается догадкой; полнота явно неизвестна. За один вызов параметры не подбираются по цене.

Модель называется `goals-sos-threshold-v2`. `rates` — интенсивности до count calibration, фактические средние нового распределения отдельно в `expected_goals`. Внутри 3+ сохраняется условная форма Poisson. Независимость голов команд, home/away team splits, fitted player effects и полноценная overdispersion остаются P1.

MEN/WOMEN и LOWER/RESERVE пересекаются по смыслу. Текущий контракт требует явного первичного профиля; двуосевая классификация не введена молча.

## Допуск и риск

Стандартная `config/research_policy.json` сохраняет BASELINE_V1/STRICT. Новая модель и GRADED включаются только через `config/p0_upgrade_policy.json`.

Отрицательная sporting sensitivity в GRADED не равна автоматически плохой цене. Но недостаточная калибровка, отрицательный epistemic low EV, конфликт, UNKNOWN, novelty, stale price, неподтверждённый holdout, отсутствие policy approval или слабая компетенция всё ещё блокируют ставку.

FRAGILE имеет потолок 50% обычного flat cap, AGGRESSIVE — 20%. Это исследовательские параметры, зафиксированные до просмотра сравнения, а не утверждённые пользователем денежные правила. Caps дополнительно снижаются портфельными ограничениями и просадкой. После проигрыша ставка не увеличивается.

Для каждого класса, лиги, рынка и модели нужен свой `stress_classes[class].passed`. Проверка включает достаточную prospective выборку, калибровку, Brier/log loss относительно baseline, стабильность двух периодов, положительный нижний интервал диагностического unit payoff, отсутствие sport veto, synthetic и retrospective capture. Обычная сертификация модели не сертифицирует автоматически FRAGILE/AGGRESSIVE.

Stress в GRADED проходит через тот же frozen calibrator, что и base. Отсутствующий калибровочный bin стресс-сценария — блокировка. Это устраняет несогласованное сравнение calibrated base с некалиброванным стрессом; STRICT оставляет прежнюю логику для регрессии.

## Честная историческая проверка

`config/p0_upgrade_design.json` фиксирует источники SHA256, policy hash и разбиение **до просмотра сравнения**:

- WARMUP: 2020/21, 380 матчей.
- TRAIN priors: 2021/22–2022/23, 760 матчей.
- COUNT_CALIBRATION: первая половина календарных дней 2023/24, 198 матчей.
- MARKET_CALIBRATION: оставшаяся часть 2023/24, 182 матча.
- TEST: 2024/25, 380 матчей.

Модель и calibrators замораживаются до TEST. Все матчи одного дня прогнозируются до добавления любого результата этого дня. Результаты предыдущих дней TEST могут войти в последующую историческую форму, но не меняют обученные параметры. Сравнение использует тот же алгоритм BASELINE_V1, что CORE 2.1/2.3, и одинаковую последующую market calibration для обоих вариантов.

TEST уже был просмотрен в прежних исследованиях. Receipt/kickoff timestamps CSV неизвестны и заменяются явно обозначенной исторической гипотезой предыдущего дня. Нет проверенных составов, травм и исполнимых котировок TEAM_TOTAL. Поэтому это проверка регрессий и вероятностей, **не независимое доказательство эффективности допуска**. Отчёт никогда не создаёт validation token.

Параметры не менялись после результата. После первого прогона исправлена согласованность stress calibration, добавлены явные блокировки отсутствующих stress bins и более точный residual bound. Исходный прогон сохранён; это технические исправления, не подбор по доходности. Первичный probability comparison от них не меняется.

Фактические цифры и ограничения финального прогона: `reports/P0_UPGRADE_HOLDOUT.json`, `reports/P0_UPGRADE_TESTS.txt` и `reports/P0_UPGRADE_REPORT.md`.

## Использование

Фиксированное историческое сравнение (каталог назначения должен отсутствовать):

```powershell
py -3 sefirot.py --policy config/p0_upgrade_policy.json p0-upgrade-benchmark --csv data/E0_2021.csv data/E0_2122.csv data/E0_2223.csv data/E0_2324.csv data/E0_2425.csv --design config/p0_upgrade_design.json --output-dir data/p0-upgrade-run
```

Источники и ожидаемые SHA256 остаются в `reports/DATA_MANIFEST.json`. Команда работает локально, без API, букмекера и базы ставок.

Fitted artifact для своей лиги/профиля:

```powershell
py -3 sefirot.py --policy config/p0_upgrade_policy.json fit-goal-model training_sports.json --samples threshold_samples.json --output data/goal_model.json
py -3 sefirot.py --policy config/p0_upgrade_policy.json capture sports.json --markets markets.json --goal-model data/goal_model.json
```

`threshold_samples.json` — список `match_id, league, competition_profile, side, rate, goals, predicted_at, kickoff, received_at, synthetic, reconstructed`. TRAIN и count calibration не пересекаются; прогноз каждого count sample предшествует результату. Любой ключ цены отклоняется. `training_sports.json` использует существующий sports contract и явно отфильтрованную историю TRAIN.

После fit artifact будущая market calibration выполняется обычными `reserve CALIBRATION`, `capture --goal-model`, `result`, `calibrate`. Следующий отдельный HOLDOUT резервируется заранее. Для capture с calibrator нужно передать также тот же `--goal-model`; его hash входит в model identity. Старые сертификаты автоматически не наследуются.

`result`/inbox RESULT создаёт audit snapshot автоматически. `closing`/inbox CLOSING и `postmortem` обогащают read view; snapshot не переписывается. `execution` только фиксирует действие человека.

## Следующий этап

API-Football подключать как нормализованный спортивный источник через уже подготовленный `API_FOOTBALL_KEY`. Здесь ключ не читался и сетевой импорт не добавлен. Источник должен сохранять fixture/team/competition IDs, профиль, phase, sports provenance и реальные timestamps; не подменять отсутствующие составы, травмы или taktical evidence пустыми подтверждёнными FACT.

До продвижения: новый prospective holdout, отдельная оценка каждого профиля/рынка/стресс-класса и сравнение с действующей моделью. Уже просмотренный TEST не использовать для выбора новых лучших порогов. Технически рабочая feature-ветка не означает готовность денежного допуска.
