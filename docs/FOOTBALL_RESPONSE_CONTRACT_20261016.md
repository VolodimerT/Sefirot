# Завершение проверки формата API-Football, 16.10.2026

База 5f78745c0982183f4a687919dfe104d25ebbec9a, существующий draft #56.

## Подтверждённые ошибки

status_summary вызывал AttributeError при null/list/string/bool/int вместо
subscription или requests. Он также переносил объекты в plan и неоднозначные
active/quota values в диагностический ответ. Строки матчей/fixture/paging
неверного типа и null score/fulltime в архивной нормализации вызывали
необработанный AttributeError. CLI не возвращал установленный отказ.

## Исправления

Только football_provider: потребляемые status containers проверяются как
objects; active — bool или unknown/None, plan — string/None, quota counters —
неотрицательные int/None без bool/str coercion. Missing остаётся None, валидные
False/0 сохраняются. План/счёт не выдумываются. Неверный status даёт фиксированный
ValueError, api-health — REQUEST_FAILED, CLI exit2 без traceback/Repository.

_rows проверяет list/object fixture containers и paging.total 0/1 с exact int.
Legacy optional paging.current по-прежнему не требуется. Прямой prematch guard
проверяет containers до .get. История FT проверяет status/score/fulltime до
чтения. Неверные входы отклоняются; score не заменяется 0:0, original packets
не исправляются/не пересохраняются. Валидная нормализация/хеши/receipts прежние.
Существующая фильтрация другого соревнования/target/не FT сохраняется.

## Проверка

Девять новых методов: owned-loopback HTTP → status_summary/api-health CLI;
синтетические sealed target/history → normalize/CLI; missing/False/0/None,
обычный Unicode, response close/один request, source bytes и отсутствие output
при отказе. Baseline red: 11 failures +49 errors с subtests; green9/9.

Дополнительная конечная матрица 546 замен consumed fields на null/bool/int/
string/list/object выполнена одинаковым скриптом на baseline и исправлении:
status42, target180, history180, Odds144. На baseline41 необработанный
AttributeError, после исправления0. Принятые варианты включают изменения
необязательных metadata; эта матрица не доказывает корректность всех API входов.
Odds container failures уже обрабатываются CLI как TypeError/ValueError без
котировок; семантика Odds не меняется. Расширение матрицы до корневых данных нашло 10 новых AttributeError в черновом
_rows: .get переместился перед проверкой root data. Добавлен root dict guard
до публикации; полный тест/релиз повторён на окончательном дереве. Это исправление
черновика не скрывается. Внешнего человека-аудитора не было.

Профильные tests, isolated full release и exact-head 20-job push+PR CI
фиксируются в итоговом отчёте. Синтетические/CI проверки не подтверждают доступ
к настоящим поставщикам, свежесть цены, HOLDOUT или эффективность модели.

Другие src/MODEL_MODULES/Policy, SQL/worker/relay/protocol, старые receipts/
seals/fits/approvals и originals побайтово сохраняются. Code hash изменяется,
model hash прежний. HTTP/auth/query/TLS/redirect/byte/budget/queue/PREMATCH и
денежные gates не меняются. Нет retry/refetch, реконструкции истории или PASS→BET.

Официальный Stake access/contract/terms и настоящий разрешённый price receipt,
реальные PREMATCH источники/независимый HOLDOUT/model edge остаются блокерами.
Hosted SQL/production/deploy/main merge требуют отдельного разрешения и не
выполняются. stake_snapshot остаётся запрещён. RESEARCH_ONLY / PASS / stake=0.
