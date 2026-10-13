# Один PREMATCH offline-путь — Issue #58

База: проверенный CORE 2.4.2 RC `22ac74911301d65e831a757222502781842c3bd9`,
draft #56, 18/18 CI jobs. Это новый небольшой инкремент поверх RC,
а не повторный перенос его стека. Exact head/CI этого этапа — в описании PR.

## Карта существующих модулей

| Участок | Используемый код | Проверенный результат и предел |
|---|---|---|
| Gateway / shared budget | football_gateway.py; test_sports_gateway.mjs; test_provider_budget.mjs | SDK query/echo/IANA и запрет redirect; SQL reserve/finish проверяются отдельно на disposable PG. Production gateway/quota не проверены. |
| Probe | scripts/chat_sports_probe.py | Canonical source packet + projection binding. В сценарии транспорт и credential только mock. |
| Archive / coverage | sports_archive.py | Исходные data + полный receipt сохраняются; exact IDs, UTC, chronology, missing context, история. Probe schema/projection_hash остаются оболочкой, импорт получает data/receipt без удаления receipt полей. |
| Source adapter | research/source_adapter_v3.py | Те же packet bytes; external origin unverified, training_rows=[]; новый fit не разрешён. |
| Seal / decide / jobs | Service + worker.process_inbox | CAPTURE до открытия price.json; DECIDE после seal; action/receipt/audit атомарны; duplicate idempotent. |
| Stake | exact_event/research_snapshot/normalize_snapshot | Exact competitors/kickoff; правила реального Stake остаются UNVERIFIED_PROVIDER_WEB_CONTRACT. |
| Chat | chat_answer_contract.py | Original decision проверяется по read-only ledger; immutable VerifiedAnswer; PASS нельзя повысить. |
| Ticket journal | исходные bets/jobs/audit | В сценарии bets пуст; OUR_TICKET=null. Наблюдение цены не является ставкой. |

## Воспроизведение

```sh
python scripts/prematch_readiness.py
python scripts/prematch_readiness.py --db /absolute/existing.sqlite --at 2030-01-01T09:02:00+00:00
python scripts/prematch_readiness.py --synthetic-e2e
python -m unittest discover -s tests -p test_prematch_path_issue58.py -v
python scripts/verify_release.py
```

Обычная команда только читает; отсутствие журнала не создаёт БД/прогноз.
Она открывает существующий ledger read-only, держит один snapshot при verify
и чтении originals, возвращает blockers и timestamp источника. Поздний cutoff
закрывает PREMATCH, оригинальный архивный PASS сохраняется.

Сценарий явно synthetic, использует отдельный новый owned temp directory,
две frozen квитанции/файла tests/fixtures/prematch_issue58 и ноль network calls.
Даты 2030 — контролируемые часы теста, не новые реальные observations.
Source hash — локальная целостность, не подпись провайдера.
Тестовые REGULATION_90 rules разрешены только в synthetic сценарии;
реальные Stake rules этим не подтверждены. Synthetic quote не выдаётся
за verified real bookmaker quote или monetarily admitted альтернативу.

Вывод различает CORE_BET, CORE_PASS, RESEARCH_ONLY, BOOKMAKER_QUOTE_OBSERVED,
OUR_TICKET. В тесте CORE_PASS/D, CORE_BET=null, OUR_TICKET=null, stake=0;
observed quote явно synthetic и verified_real=false.

## Подтверждённые ошибки и изменения

До исправления нормализатор выпускал FT TOTAL при period=1H,
две HOME записи как полную 1X2 partition и TOTAL 2.5 при названии Over 3.5.
Теперь main scope требует known main/total group и exact specifiers, полную
различимую partition и совпадение outcome line/specifier. Неизвестный scope,
half/ET, repeated sides, wrong line/sign отклоняются без partial mapping.
Первый local release обнаружил две совместимости: известная группа total
нужна Builder, а отсутствующий line specifier должен сохранить прежнюю
ошибку atlas. Исправлены входные ветви mapper; исходные тесты не ослаблены.
Повторный полный release прошёл.
Первый CI head 55425f459aa3ba9d7dbefdb84b47ef8a49a5b074 выявил ошибку
cleanup нового adversarial теста на обеих Windows конфигурациях:
sqlite3 connection context manager не закрывает соединение. Тест теперь
использует closing + explicit commit, сохраняя проверку metadata/chat.
Runtime/модель ради этого не менялись; новый head проходит полный CI заново.
Это non-model исправление stake_mapper.py: code_hash меняется явно;
семь MODEL_MODULES/Policy и прежние reports/seals не переписаны.

## Проверки

18 новых интеграционных/регрессионных тестов: исходная цепочка и replay,
immutable originals, ноль сети/ставок, first price read after seal,
wrong fixture/period/status/rules/late data, stale price, quota exhausted/
unknown, missing shared-budget marker, duplicate job, changed SQL metadata,
missing source/context/calibration/HOLDOUT, no data/read-only и closed window.
Коды ошибок CORE используются исходные (stale price = PRICE_STALE).

Adversarial redirect/token leakage и реальный reserve/finish не имитируются
новой параллельной реализацией: полный CI выполняет существующие
test_chat_store.py, test_stake_provider.py, test_sports_gateway.mjs (41 cases),
PostgreSQL budget suite (10, 16 callers), test_coherence_admission_v51.py,
test_batched_integrity_v5.py и PostgreSQL mirror (5). Joint conflict проверяется
существующим CORE gate; builder marginal multiplication не добавляется.

Полный release: 1313 тестов, 1309 passed + 4 PostgreSQL skipped в общем прогоне.
Mirror/budget отдельно обязательны в exact-head CI; skips не выдаются за pass.
Synthetic lifecycle integrity/replay=true. CI Ubuntu/Windows × 3.11/3.13,
mirror и budget — ссылки и окончательные результаты в описании draft PR.

## Реальные блокеры

API_FOOTBALL / STAKE / GATEWAY / SUPABASE_STORE: NOT_VERIFIED,
checked_at=null, quota=null. Исторический account suspended от
06.10.2026 16:18:54 UTC (Issue #29) выводится отдельным историческим фактом.
Статус кода AVAILABLE не равен доступности runtime/API.
Readiness не читает credentials/config/vault и не делает /status запрос.

Не хватает independently verified permitted source origin/coverage,
новых real fixtures/receipts/lineups, real timestamped Stake quote/rules,
CALIBRATION и заранее назначенного независимого HOLDOUT, runtime auth/store
и owner authorization для будущей проверки сети. Поэтому real money/execution
закрыты; неизвестность остаётся PASS/D/0 или отсутствием прогнозов.
main/production/deploy/секреты/платные API не изменяются.

После зелёного exact-head CI — #59: честный evidence audit и prospective plan.

Identity текущего инкремента: code_hash `63bf9d3dce9eb57db63ca5761a1df71648b2171b72b45ad6b21abcc4308448cd`; model_hash `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`; policy_hash `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`.
