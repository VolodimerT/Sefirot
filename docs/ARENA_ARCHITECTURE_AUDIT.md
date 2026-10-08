# ARENA: фактическая проверка, 08.10.2026

Новая ветка основана на реальном PR #13:
19a81f961ded4477a08da89d20ee584f35738f8f. PR #12:
59c02bc5ccef16db22cd092ecb4328adeb0708f0; PR #11:
053ad5a07c4732c5062ac6a445fc1d61b1c2a119. Архивные
arena_shadow.py/arena_forward.py и схемы v0/v1 сохранены побайтно.

| ID | Дефект базы | Новое поведение / ограничение |
| --- | --- | --- |
| A-01 P0 | run_arena: любой BLOCK закрывал весь pool | arbitrate: HARD_BLOCK привязан к market; системные нарушения остаются глобальными |
| A-02 P0 | status/explanation не связывали возражение с предпосылкой | validate_findings: точные поля, sealed market/premise/fact IDs, время, confidence label, source families |
| A-03 P0 | _view передавал raw sports | sports_view: Core inspect/eligible_history/used_history, allowlist и структурные summaries без raw nested text |
| A-04 P0 | hash/created_at self-attested | LOCAL_LEDGER_BOUND отдельно от внешней аутентификации; unbound → PROVENANCE_UNVERIFIED. Manifest/time остаются self-attested, prospective_validated=false |
| A-05 P0 | сравнение только NAIVE/ARENA | RO bridge фактических original PASS/BET и RECORD binding, exact seal/cutoff/quotes; три arms, missing original ≠ PASS |
| A-06 P1 | повтор факта мог выглядеть независимым | FACT→premise→market graph, exact source families, reviewer IDs запрещены. Causal model не реализована |
| A-07 P1 | offline без real cost | RULE_ONLY/REPLAY, gpt_calls=0; CUSTOM_SHADOW count/cost=null. Live LLM adapter/budget/latency пока отсутствуют |
| A-08 P1 | win rate без цены пропуска | planned/capture/decision/quote/result coverage, hypothetical utility, rejected profitable/unprofitable как hindsight; нет real ROI/CLV/cost доказательства |
| A-09 P1 | один SHA: success push / failure PR CI | конкретный Windows stacktrace получен, bounded POST teardown исправлен; повторная матрица в test report / PR |
| A-10 P2 | schedule/risk/public trap предполагались | RULE_ONLY показывает UNKNOWN и missing input, данные не выдумываются |

Дополнительный P0: v0 _candidate_rows считал stress как
(odds−1)*win+push−1, то есть верный EV минус win. Low bounds не обязаны
суммироваться в один. v0.2 вызывает неизменный Core ev_bounds и использует
WIN*(odds−1)−LOSS для stress vectors. Архивные результаты не переписаны.

## Windows CI

Оба исходных runs имеют head 19a81f961ded4477a08da89d20ee584f35738f8f:
[push 37754281186](https://github.com/VolodimerT/Sefirot/actions/runs/37754281186)
успешен; [PR 37754287501](https://github.com/VolodimerT/Sefirot/actions/runs/37754287501)
неуспешен. Job 113234885631, Windows/Python 3.11: 612 tests, errors=2.
test_only_valid_origin_and_session_token_can_process_jobs и
test_wrong_host_rebinding_and_duplicate_host_are_rejected получили
ConnectionAbortedError / WinError 10053 на HTTPConnection.getresponse.

Handler.do_POST отклонял Host/Origin до чтения тела и закрывал соединение.
Это соответствует описанному в
[RFC 9112 §9.6](https://www.rfc-editor.org/rfc/rfc9112.html#section-9.6)
риску потери HTTP-ответа при unread request data. reject_post удаляет только
однозначное тело до 4096 B с timeout 0.25 s, затем отправляет отказ.
Worker не вызывается, processing body limit остаётся 512 B. Не читаются
chunked, duplicate Content-Length или большие тела. Два deterministic
контрпримера проверяют discard-before-response и границы; старые guards
сохранены. Packet capture исходного run отсутствует: единственность причины
не доказана, окружение runner не исключено.

Это единственное production изменение внутри src/sefirot в данном этапе:
локальный HTTP transport для A-09. Семь MODEL_MODULES, Policy, Service/SQLite,
CLI workflow и money gates побайтно прежние. Core hash изменён; старые seals
воспроизводить в архивной сборке. Нет новой реальной когорты, LLM вызовов
или подтверждения доходности; новые SQLite tests используют настоящий Core.
