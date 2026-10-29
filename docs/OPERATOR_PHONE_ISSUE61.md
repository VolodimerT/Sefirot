# Phone-first read-only cockpit — Issue #61

База verified #59/#63 `b1961710bcb0634e40e013260a4c38d963bad1a4`;
зависимости #57/#58 проверены. Панель не зависит от исследований #60.
Переиспользуются existing chat_gateway.Handler (safe responses/logging),
prematch_readiness и original chat verifier/immutable repository.
Existing manual inbox остаётся отдельной action-capability; новая страница
никогда не вызывает worker, execute/status (который мог создать БД) или demo.

## Что получает владелец Android

Минимальный адаптивный прототип web/operator/index.html, CSS и module JS.
Данные читаются только из authenticated /api/operator. Login выдаёт короткую
HttpOnly/SameSite=Strict cookie; пароль сразу очищается, localStorage нет.
JS/HTML не содержат provider/bridge keys или личных отчётов.
Сначала видны UNAVAILABLE/NOT_VERIFIED; fake fixtures, fake stats и fake CI
не подставляются. No data — нет оригинальных записей, не synthetic forecast.

Панель показывает version/code/model/policy hashes, actual local git HEAD/
branch и CI=NOT_VERIFIED без runtime receipt. Это honest unknown, не красный CI
и не обещание подключённого backend. Provider statuses/timestamps/quota берутся
из read-only readiness; unknown quota=null. Historical suspended отделён
от текущего NOT_VERIFIED.

Original verified decision cards дают match/market filters, CORE PASS/BET,
grade, исходные model/implied P/EV, tactical/public-trap/death-test только если
они реально сохранены; missing fields=UNAVAILABLE. Research candidate отдельно.
Журнал/IDs не меняются; portfolio/bankroll/private request inputs не выводятся.
Archive_only/fresh_quote_attested=false: это исходное решение, не новая цена.
Build mismatch сохраняет original hash/PASS и показывает блокер.

## Доступ с телефона сейчас

Cloud runtime **не подключён**, URL для живой частной панели не существует.
Владелец не должен запускать Python на Android или иметь ПК.
Для ознакомления можно открыть файлы прототипа/скрин локального review:
без backend они честно показывают недоступность. Полностью функциональное
подключение требует отдельного разрешения на private hosting/runtime/auth;
тогда мобильный браузер открывает согласованный HTTPS URL, вводит код доступа
и работает без локального Python. В этом этапе hosting/deploy не выполнялись.

Команды ниже — для разработчика/CI review, не обязанность владельца:
```sh
python -m unittest discover -s tests -p test_operator_cockpit_issue61.py -v
node scripts/test_operator_cockpit.mjs
python scripts/verify_release.py
python scripts/operator_cockpit.py --db /absolute/existing.sqlite --port 8787
```

Последняя команда требует существующий owner-provisioned bridge token через
existing configured_token; агент не читал/создавал/менял реальный secret.
Test factory получает только SYNTHETIC_OPERATOR_TEST_ONLY token.
Сервер **только 127.0.0.1**. Cookie без Secure — строго локальный HTTP review,
не production configuration. Реальный remote HTTPS/proxy/session wiring ещё
не авторизован и не установлен; локальный URL не доступен Android автоматически.
Не запускать legacy Render runner или провайдеры ради этой панели.

## Проверки и ограничения

8 Python tests и 8 frontend assertions: absent/no data without DB creation,
401/403, wrong-origin/login/expiry, HttpOnly cookie, authenticated read,
POST/PUT/PATCH/DELETE paid-fetch/policy/LIVE/queue refusal, actual original
PASS/D and market data, no writes/secrets/static action controls, stale archive,
current build hash mismatch. Node выполняет реальный renderer с минимальным
DOM harness: SOURCE BLOCKED, no-data, filters, research separation, PASS,
mismatch и missing vs true zero. Это не тест реального Android браузера.

Full local release: 1339 tests = 1335 pass + 4 общих PostgreSQL skips,
integrity/replay=true. Exact-head OS/Python/actual PG CI — итог в draft PR.
Все src/sefirot/MODEL_MODULES/Policy, старые seals/reports/source/approvals
побайтно прежние; changes только research operator projection, transport
subset, frontend/tests/docs. CORE code_hash остаётся #59.
main/production/paid APIs/secret rotation/money/LIVE не менялись.

## Подтверждённое исправление сессии, 14.10.2026

На исходном #64 `0f7132ae664101aff96fb21754dac3ce8c599dc8` реальный
JS обработчик после HTTP 401 оставлял прежние карточки/журнал на странице
и в памяти фильтров. API корректно отказывал: ошибка находилась в интерфейсе.
Синтетический сценарий воспроизвёл оба случая до исправления.

Теперь 401/403/ошибка сервера, транспорта или JSON очищают карточки,
research, журнал и состояние фильтров. Повторный login сначала очищает
прежние данные. Более ранний ответ или чтение JSON не могут вернуть
карточки после нового отказа; старый 401 не скрывает более новый успешный
ответ. Повторное разрешённое чтение восстанавливает исходный PASS.

Регрессия выполняет реальные обработчики модуля в Node DOM harness,
12 сценариев: отказы, неисправный ответ, порядок конкурентных запросов,
failed login и recovery. Fetch заменён синтетическими ответами, provider
запросов и реальных ключей нет. Это всё ещё не проверка Android браузера.

```sh
node scripts/test_operator_session.mjs
python -m unittest discover -s tests -p test_operator_cockpit_issue61.py -v
python scripts/verify_release.py
```

Исходные 8 renderer cases и HTTP permission tests сохранены. Добавлена одна
Python регрессия, запускающая 12 session cases. Точный итог повторного
полного release/CI публикуется в существующем draft PR #64. CORE code_hash,
model_hash/policy_hash, src/sefirot и прежние отчёты/квитанции неизменны.

Повторный изолированный локальный release: 1340 тестов = 1336 успешных
+ 4 PostgreSQL skips без DSN; demo integrity/replay=true. Текущий CI
проверяется отдельно на точном обновлённом HEAD #64.
