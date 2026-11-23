# SEFIROT 4.5 — сбор и проверка SHADOW-прогнозов

Pipeline использует исходный Repository, API-Football gateway, Policy и существующий forward scorecard. История и вероятности сохраняются в двух выделенных SQLite-файлах. Сценарий запускается из корня checkout. Все команды, кроме явно разрешённой `collect`, работают без сети.

## Команды оператора

```bash
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite import /path/to/original.json
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite plan-next --league 61 --profile MEN --source-reliability 0.8
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite enqueue 1552830 --profile MEN --source-reliability 0.8
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite capture
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite settle
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite report --text
```

Используйте один из способов выбора. `plan-next` проверяет ближайшие кандидаты в указанной лиге и ставит в очередь максимум один допущенный fixture. `enqueue` выбирает известный ID для адресного сбора. Оригинальный сезонный или дневной пакет служит для обнаружения матчей и истории. Для seal нужен свежий отдельный ответ на `fixtures?id=...`. Используйте JSON без `--text` для журнала оператора. Флаги профиля и надёжности фиксируют явные параметры источника, заданные оператором.

`capture` и `settle` можно вызывать существующим планировщиком по очереди с теми же путями к SQLite. Сначала стоит проверить один матч. Повторный проход не создаёт второй прогноз или повторный scorecard. Проходы ограничены числом изменений состояния. Записи о плане и seal коммитятся вместе с доказательством захвата. FT и scorecard коммитятся вместе. После сбоя достаточно снова запустить локальный проход. Для нового состава source receipts сохраняются время первой доступности, SHA оригинала и хеш входного пакета. Старые решения и чужие журналы не импортируются в SHADOW-реестр.

### Один запрос с явным разрешением

Существующий администратор бюджета открывает ограниченное окно в штатном gateway. Укажите уникальный alphanumeric ID разрешения и фактический срок действия с часовым поясом, максимум 15 минут от запуска. Пример команды намеренно использует заполнители вместо истёкшего или выдуманного разрешения.

```bash
python scripts/prospective_shadow.py --db data/shadow.sqlite --source-db data/shadow-sources.sqlite collect --phase NS --fixture-id 1552830 --approval-id OWNERAPPROVALID --expires-at APPROVED_ISO_INSTANT
```

Для FT используется отдельное разрешение и тот же ID матча с `--phase FT`. Сбор запускается после окончания матча. До истечения 90 минут от kickoff FT-запрос исключён также программно. Для расписания используйте `--phase calendar --date YYYY-MM-DD --league ID --season YYYY` с отдельным разрешением. Gateway остаётся единственной точкой расхода. При потере ответа идентификатор разрешения считается использованным. Для безопасного восстановления сначала проверьте вручную сохранённый источник и состояние бюджета. Повторный сетевой запрос требует нового разрешения. По умолчанию сохраняйте команды автоматизации локальными.

## Критерии данных и оценки

- Применяется текущее ограничение свежести и минимум истории каждой команды из Policy. Первый локальный импорт и QC предшествуют cutoff. Смена времени, fixture identity, спорный результат и отзыв прежнего статуса FT остаются в журнале как причины отказа.
- xG, составы и травмы отсутствуют во входе исходной голевой модели, пока не доказаны источник, время и семантика. Опциональные отсутствующие сведения видны в журнале и сохраняют PASS для ставок. Пустые значения не заполняются.
- Прогнозы получают роль `CALIBRATION` до seal. Сырые оценки подходят для будущего сбора при соблюдении требований fit gate. Покрытие и независимый HOLDOUT остаются отдельными условиями. История исходной модели, параметры, котировки и исходы после cutoff не подмешиваются.
- Scorecard использует Brier и log loss существующего forward-зачёта с baseline по замороженной истории. Накопительные метрики разделены по сборке, модели, Policy, лиге и контракту. Семь контрактов одного матча считаются одним fixture. FT-исправление исключает матч из актуального scorecard и блокирует его в штатном fit gate, исходные данные сохраняются.
- Мобильный текстовый отчёт показывает архивное расписание, свежесть, seal, ожидание FT, причины PASS и последний зафиксированный ответ gateway, если он есть. Текущий остаток shared budget не выводится из старого ответа провайдера.
- Ставки, LIVE, EV и fit в этом процессе отключены. Внешний архив подтверждает локальную целостность пакетов, а не криптографические подписи провайдера.

## Воспроизведение

```bash
PYTHONPATH=src:tests python -m unittest test_prospective_shadow -v
python scripts/verify_release.py
```

`test_full_cycle_with_restart_and_disputed_result` выполняет цикл на данных **SYNTHETIC_TEST_ONLY**. Его scorecard исключён из калибровочной диагностики. Для оригинала «Брест — Париж ФК» использован сохранённый receipt от 7 ноября с SHA-256 `1408fd0a2f315285e24f66e5cb8413accbfb8aa30e821489e49a13475b513eff`. Прогон через `import → enqueue → capture → settle → report` вернул `NEEDS_DATA / STALE_TARGET_OBSERVATION` и 0 прогнозов. Это проверка реального архивного источника и fail-closed поведения. Для нового настоящего seal нужен свежий оригинальный receipt.
