# SEFIROT S1.1 — расписание SHADOW

Один проход `tick` использует существующие планирование, capture, settle и report. Он работает офлайн, использует одну транзакцию для прохода и сохраняет время следующей попытки в SQLite. Обычный интервал составляет 30 минут, при недоступности входов действует пауза 15, 30 или 60 минут. Фактическая частота зависит от подключённого планировщика. Повтор в пределах этого окна не создаёт циклов или прогнозов. При аварии незаписанный проход откатывается, а повтор использует исходные receipts и существующую дедупликацию.

## Запуск планировщиком

```bash
python scripts/shadow_checkpoint.py restore state SHADOW_STATE.zip
python scripts/prospective_shadow.py --db state/shadow.sqlite --source-db state/sources.sqlite tick --league 61 --profile MEN --source-reliability 0.8
python scripts/prospective_shadow.py --db state/shadow.sqlite --source-db state/sources.sqlite report --text
python scripts/shadow_checkpoint.py pack state NEXT_SHADOW_STATE.zip
```

Работайте в свежем каталоге с зафиксированным SHA. Для удалённого планировщика используйте одну приватную копию ZIP с двумя журналами и обновляйте её только с проверкой ожидаемой версии. При конфликте версии отвергните локальный результат и восстановите текущую версию на следующем проходе. При восстановлении проверяются SHA-256 и целостность обоих SQLite. Для оператора отображайте время последнего сохранённого receipt, статус SHADOW, seal, ожидание FT и Brier/log loss. Текущий статус бюджета можно сверить в Supabase чтением только метаданных.

## Одноразовый NS для «Брест — Париж ФК»

Fixture `1552830`, 27.11.2026, 21:45 по Киеву. Повторно сверить официальный kickoff непосредственно перед вызовом. Окно свежести начинается 26.11 в 21:45 по Киеву. После отдельного разрешения владелец использует штатный `sefirot_budget_private.arm_research_budget(1,5)` и отдельный идентификатор разрешения. Из той же текущей копии журналов, которую использует планировщик:

```bash
python scripts/prospective_shadow.py --db state/shadow.sqlite --source-db state/sources.sqlite collect --phase NS --fixture-id 1552830 --approval-id "$OWNER_NS_APPROVAL_ID" --expires-at "$OWNER_NS_APPROVAL_EXPIRY"
python scripts/prospective_shadow.py --db state/shadow.sqlite --source-db state/sources.sqlite capture
python scripts/prospective_shadow.py --db state/shadow.sqlite --source-db state/sources.sqlite report --text
```

Сверить время и исходную идентичность пакета, затем сохранить обновлённый checkpoint с проверкой версии. Если исходный receipt отсутствует, устарел или изменились расписание, идентичность либо хронология, вывод содержит фактическую причину отказа. По завершении матча требуется отдельное разрешение и новый идентификатор для `collect --phase FT --fixture-id 1552830`. Следом запускаются `settle` и `report --text`. При неопределённом результате сетевого запроса повтор с тем же разрешением запрещён. Во время ручного обновления checkpoint приостановите планировщик, чтобы его запуски использовали последнее подтверждённое состояние.
