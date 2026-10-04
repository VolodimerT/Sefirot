# Будущая API-выборка: сбор, а не сертификат

Сборка 05.10.2026 добавляет `forward-plan`, `forward-capture`,
`forward-settle`, `forward-status`. CORE 2.4.2, BASELINE_V1/STRICT и
вероятностная модель сохранены. 382 локальных теста и release gate прошли;
удалённый CI проверять на последнем head PR #9.

code_hash: `28d99e80359ff84329e918ba76a96357384c0b8f138b4be7572f6edf9941dd03`.
model_hash: `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`.

## Что фиксируется заранее

`forward-plan` принимает неизменённый API-Football packet с receipt,
явно заданные league ID → competition profile и операторскую оценку
надёжности источника. Он включает **все будущие NS-матчи указанных лиг
в этом packet**, не смотрит цены или вероятности и атомарно записывает
план и split assignments до первого прогноза. Остальные строки учитываются
в excluded_counts. Выбор лиг и профилей остаётся операторским решением;
классификация профиля и reliability не объявляются независимо измеренными.

Фиксируются build/model/policy/calibrator, состав матчей, kickoff, IDs команд,
семь DEFAULT_POOL контрактов и hash исходного packet. Это базовый пул с одним
кандидатом на семейство, а не расширенная сетка 50 контрактов. Текущий сборщик
поддерживает BASELINE_V1; prospective сравнение SOS_THRESHOLD_V2 сюда ещё
не включено. Сбор исследования ведётся в отдельном SQLite без production routes.

| Этап | Условие | Значение |
|---|---|---|
| CALIBRATION | Без calibrator | Сначала собрать и рассчитаться по сырым прогнозам |
| HOLDOUT | Совместимый nonsynthetic calibrator уже заморожен | Только новые матчи вне fit_ids |
| validate | Точная версия модели и политики, результаты HOLDOUT | Существующие проверки контекстов; не выполняется автоматически |

Количество матчей в плане не равно количеству наблюдений для допуска.
Порог min_holdout=60 применяется к контексту, а min_calibration=20 — к
конкретному калибровочному bucket. 60 матчей суммарно по разным лигам,
профилям и рынкам не закрывают эти требования. Связанные рынки одного
матча не считаются независимыми матчами. Существующие статистические
проверки не изменены и их ограничения по зависимости наблюдений сохраняются.

## Команды в PowerShell

API-ключи остаются в защищённой локальной конфигурации. Вызов `football-fetch`
требует API_FOOTBALL_KEY; ключ, имеющийся только в Supabase Vault, локальная CLI
сама не извлекает. Примеры ниже выполняются для **нового будущего** packet.
Дату и IDs лиг выбирают до просмотра прогнозов и результатов.

```powershell
py -3 sefirot.py football-fetch --endpoint fixtures --param date=2026-10-06 --param timezone=Europe/Kyiv --output data/fixtures-next.json
py -3 sefirot.py football-archive data/fixtures-next.json --directory data/forward-archive
py -3 sefirot.py --db data/forward.sqlite forward-plan data/fixtures-next.json --league-profile 5=MEN --league-profile 141=MEN --source-reliability 0.8 --output data/forward-plan.json
$study = Get-Content data/forward-plan.json -Raw | ConvertFrom-Json
py -3 sefirot.py --db data/forward.sqlite forward-capture $study.id --directory data/forward-archive --output data/forward-capture-001.json
py -3 sefirot.py --db data/forward.sqlite forward-status $study.id --output data/forward-status-001.json
```

Доступную свежую FT-историю сначала получают обычным `football-fetch` и
добавляют в тот же архив. Он обязан содержать оригинальный selection packet.
Каждый повтор capture получает новый output filename; уже сохранённый
прогноз не пересчитывается. Пропущенное окно не восстанавливается replay.

`forward-capture` пытается обработать каждый плановый матч. Недостаток
истории обеих команд до min_team_games=8, устаревший target snapshot,
изменившийся kickoff/identity или отсутствие данных сохраняются в attempts.
При достаточной истории создаётся research seal; другие sporting blockers
показываются отдельно и не превращаются в денежное разрешение.
Нельзя незаметно добавить рынки, заменить fit, включить production route
или перенести исследование на другую сборку. Старый план можно прочитать
через forward-status; продолжать расчёт надо на его архивной версии.

После завершения матчей получить новый API packet и выполнить:

```powershell
py -3 sefirot.py football-fetch --endpoint fixtures --param date=2026-10-06 --param timezone=Europe/Kyiv --output data/fixtures-results.json
py -3 sefirot.py --db data/forward.sqlite forward-settle $study.id data/fixtures-results.json --output data/forward-results-001.json
py -3 sefirot.py --db data/forward.sqlite forward-status $study.id
```

Принимаются только точные IDs команд/матча, неизменённый kickoff и FT с
regulation fulltime score. AET/PEN, отмена и перенос не объявляются
результатом или VOID автоматически. `finished_at` — верхняя граница по
времени получения FT, а не выдуманное время финального свистка.
Исправление уже принятого счёта требует review; feedback не переписывается.
Ручной результат нельзя переименовать в первоначальное API-доказательство.
Квитанция API сохраняется до settlement, поэтому прерванный batch можно
продолжить, сохранив источник уже записанных результатов.

Затем `calibrate` создаёт frozen artifact из CALIBRATION records. Только
после этого резервируют **новый** future packet с `--role HOLDOUT
--calibrator HASH`. Заморозка fit не означает, что bins или holdout прошли.
`forward-status` показывает весь исходный знаменатель и всегда оставляет
holdout_passed=false; денежный допуск проходит существующую отдельную процедуру.

## Реальная проверка на 05.10.2026

В 21:04 UTC 04.10 (00:04 Kyiv 05.10) API-Football ответил и вернул 99 NS-матчей
на 5 октября. В 21:05 UTC запрос истории лиги 128, сезон 2026, FT был отклонён
Free-планом: доступны сезоны 2022–2024. HTTP 200 с provider errors не принят
как успешная история. В проверенной локальной конфигурации и известных
provider entries проекта Supabase ключ The Odds API отсутствует.

До прогнозов в отдельном журнале зарезервированы 17 будущих матчей семи
заранее выбранных лиг, роль CALIBRATION. Прогон на двух уже полученных API
packets дал **17 INSUFFICIENT_HISTORY, 0 новых seals, 0 prospective results**.
Журнал целостен. Данные старых сезонов не подставлялись вместо текущей формы;
просмотренные ранее матчи не переименованы в holdout. Личные SQLite, исходные
API packets и служебные отчёты этого прогона хранятся отдельно от Git.

Это проверка работающего сбора и отказа при недостаточных данных, не оценка
доходности. Для содержательного продолжения нужны доступная свежая история
и подключение API коэффициентов. Команды не запускают круглосуточный сервис.
Локальные hashes фиксируют содержимое, но не являются подписью провайдера
или независимой внешней отметкой времени. MAIN не обновлён.
