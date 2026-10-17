# Рабочая исследовательская версия CORE 2.4.2

Единый источник — существующий draft PR #56. База этого этапа:
`5990c6b079d4de0c716c28a33d809cff45166a4e`. Точный новый HEAD/tree и результаты
CI записываются в паспорт готового пакета после его проверки. Наличие этого
файла не означает, что Render/Supabase уже обновлены.

## Что поставляется

Полный source ZIP содержит точные tracked files одного коммита: `src`,
`sefirot.py`, `research`, `scripts`, `web`, SQL, тесты и документацию. Рядом —
машиночитаемый паспорт сборки, manifest SHA-256 всех исходников и подтверждение
exact-head CI. Это полный рабочий исходный пакет, а не прежний review ZIP с
несколькими изменёнными файлами. Он не включает `.git`, `.env`, credentials,
runtime data, оригинальный ledger или фотографии токенов.

Wheel `sefirot_core-2.4.2-*.whl` устанавливает самодостаточный CORE CLI.
Он отдельно проверяется в чистом venv. Он не содержит `research/scripts/web`,
поэтому запуск панели и полного research/SQL CI выполняется из source ZIP.
Обычный setuptools sdist также не содержит этих частей; использовать его
как полную поставку исследовательской системы нельзя. Это ограничение
упаковки, не ошибка основных console-команд wheel.

## Запуск без API

Для разработчика: распаковать весь source ZIP, перейти в его каталог. Нужен
Python 3.11+; стандартного Python достаточно для локального чтения. Полный CI
дополнительно использует Node/PGlite и отдельные PostgreSQL зависимости.

```sh
python sefirot.py build-info
python scripts/prematch_readiness.py
python sefirot.py --help
```

Эти команды не запрашивают провайдеров. Отчёт без подключённого ledger честно
показывает NOT_SUPPLIED/NOT_VERIFIED. Пустые данные не заполняются demo-матчами.
Для установленного wheel эквивалент паспорта — `sefirot build-info`.

`python sefirot.py demo`, `START_SEFIROT.bat` и `--synthetic-e2e` — только
тестовые синтетические сценарии, не реальные рекомендации/качество модели.
Исторические tracked reports в source сохраняются как история; свежие проверки
поставки и CI находятся в её отдельном паспорте, не подменяют старые отчёты.

## Защищённый локальный просмотр

Владелец или администратор заранее настраивает существующий
`SEFIROT_BRIDGE_TOKEN` через приватное окружение процесса: 32–256 печатных
ASCII-символов без пробелов, высокоэнтропийный код. Это код просмотра, не
Stake account token и не provider API key. Не вставлять его в команду URL,
frontend, отчёт, GitHub или shell history. Скрипт не создаёт/меняет реальные
секреты и не печатает их значения.

```sh
python scripts/operator_cockpit.py --db /absolute/existing.sqlite --port 8787
```

После успешного bind печатается действительный адрес `http://127.0.0.1:PORT`.
`--port 0` выбирает свободный порт; выводится фактически выделенный номер.
Отсутствующий/неверный код, занятый порт и номер вне 0..65535 дают exit2 и
понятную ошибку без traceback/значения кода. Запуск не открывает входящие
соединения на внешнем интерфейсе. Для остановки — Ctrl+C.

Если `--db` не задан, показывается отсутствие подключённого ledger. Несуществующий
путь отображается ABSENT без создания базы. Передавать только отдельно
согласованный original ledger/backup; не импортировать synthetic сценарии в него.
Панель сохраняет архивные решения/PASS, недоступные legacy IDs, unknown/stale
котировки и missing values. Архивный BET не является новым разрешением на ставку.

Без входа данные закрыты401; запись, LIVE, очередь и платный сбор закрыты403.
Session cookie HttpOnly/SameSite=Strict, локальный HTTP только на loopback.
Извлечённый ZIP не содержит `.git`: runtime HEAD/CI могут отображаться
NOT_VERIFIED, что правильно. Точные опубликованные SHA/CI сверять с паспортом,
не превращать отдельный manifest в выдуманный authenticated runtime receipt.

Локальный адрес не доступен автоматически с Android. Владельцу не нужен ПК
или Python на телефоне: для телефона потребуется отдельно разрешённый
согласованный HTTPS runtime, auth/session и hosted проверка. Публичный адрес
панели пока не существует; запуск локального сервера не выдаётся за deployment.

## Реальные источники и качество

Официальная OpenAPI/auth/terms/лимиты Stake недоступны для подтверждения:
BLOCKED_BY_STAKE_ACCESS. Аккаунтный token не заменяет Sports Data key, другой
букмекерский источник не переименовывается в Stake. Для одного реального
quote test нужны подтверждённые права и отдельное разрешение владельца.

Последний проверенный бюджет API-Football: QUOTA_STOP/enabled=false,
remaining5/reserve5, срок15Oct09:16:57UTC истёк. Это историческое наблюдение,
не свежая проверка квоты при запуске. У56 сохранённых fixture IDs нет полных
original packets пяти запросов; verifier корректно отказывает. Statistics,
genuine Stake quote, результаты/независимая калибровка/HOLDOUT не подтверждены.
Brier/LogLoss/ECE остаются null/NOT_VERIFIED; small markets SHADOW, PASS/stake0.

## Установка подключённого runtime

Использовать существующий
[rollout/rollback](P0_B_ROLLOUT_AND_ROLLBACK_20261015.md): reviewed incremental
SQL migration с parked queue, matching relay/worker, проверка оригинального
архива и ACL/RLS, затем отдельное разрешение на ограниченное окно сбора.
Fresh-install SQL поверх populated Supabase не применять. Rollback паркует
обработку и сохраняет receipts/attempts, не сбрасывает budget и не возвращает
unfenced completion. Точный проверенный код выбирается по паспорту поставки.

Merge main, production deploy, hosted writes, secret changes, budget activation
и реальные API-запросы в этой поставке не выполняются.
