# Контракт локальных данных

Формат `examples/core2_case.json` содержит раздельные sports / markets / quotes / recheck / result. Для рабочего CLI сохраните эти поля в отдельные файлы: котировки загружаются после capture.

- Везде ISO 8601 с часовым поясом. naive timestamp запрещён.
- `match`: стабильные ID матча/команд, лига, kickoff, `sport=football`, `format=REGULATION_90`.
- `match.competition_profile`: `MEN / WOMEN / RESERVE / LOWER / UNKNOWN`. Пропуск означает UNKNOWN и блокирует денежный допуск. Профиль назначается явно поставщиком; система не угадывает его по названию команды. Популяция и уровень лиги могут пересекаться: неоднозначные случаи до отдельного решения оставляются UNKNOWN.
- `as_of`: срез доступного спортивного знания, не будущее по локальным часам.
- `sources`: ID, группа независимости, reliability 0..1, enabled. Это оценка поставщика, а не автоматическая гарантия достоверности.
- `evidence`: ID/key/value, FACT/INFERENCE/ASSUMPTION, source_id, observed_at ≤ published_at ≤ received_at ≤ as_of, critical, supports. Supports ссылаются на ранее доступные FACT; циклы запрещены.
- Обязательные ключи: home_team, away_team, format, lineup, injuries, coach, rotation, tactics. Lineup содержит status CONFIRMED и уникальные 11 ID игроков с каждой стороны. Травмы — списки для home/away. Tactics: home_style, away_style, fit SUPPORTED, key_factor. Изменения этих фактов требуют нового seal.
- `history`: id/home/away/league, kickoff < finished_at ≤ received_at, целый неотрицательный счёт, source_id. Недоступные на as_of результаты исключаются. Целевой матч запрещён в истории.
- История должна иметь тот же `competition_profile` и лигу, что целевой матч. Пропущенный профиль считается UNKNOWN, а не MEN. Диагностический opponent-strength trace использует только результаты, полученные до kickoff конкретного исторического матча; эти веса пока не участвуют в вероятности.
- Дополнительное evidence `key=matchup_signal` — только INFERENCE с `value.status=CONFLICT/CONSISTENT` и supports на доступные надёжные FACT. CONFLICT требует UNKNOWN/RECALCULATE. Система не обнаруживает H2H-конфликт сама из произвольного текста.
- Необязательный `sports.thesis_links`: список `{id, markets, premise_ids}`. Связывает 2–7 ключей из заранее объявленного пула с подтверждёнными спортивными предпосылками. Связи запечатываются до цены. Рост коэффициента связанного исхода на исследовательский порог вызывает проверку всех этих рынков; это сигнал проверки, а не доказательство ложности тезиса.
- `markets`: 1–7 кандидатов, по одному на семейство, объявленных без цены.
- `quotes`: market, bookmaker, decimal odds >1, observed_at ≤ received_at, phase OPEN/FINAL/ENTRY/CLOSE, rules REGULATION_90. OPEN/FINAL/ENTRY входят после seal. CLOSE — только постматчевый аудит. `line_id` связывает полную 1X2 линию.
- Полная одновременная линия одного БК позволяет proportional no-vig сравнение 1X2, DNB, форы, тотала, ОЗ и индивидуального тотала. Целые линии сравниваются условно при отсутствии PUSH. Одиночная цена явно называется break-even proxy и не считается sharp consensus. Исследовательский порог extreme_divergence=0.20 требует нового спортивного seal.
- Необязательный `fetch-odds`: только полная 1X2 одного выбранного букмекера после seal. Требует точного ID события, команд и kickoff; время обновления поставщика обязательно, `--rules-confirmed` подтверждает проверку условий расчёта. Квитанция содержит источник и отмечает, что цена в аккаунте не подтверждена.
- `recheck`: checked_at и новый полный набор evidence. Простого поля «проверено=true» недостаточно.
- `result`: match_id, FINISHED/VOID, home_goals/away_goals, finished_at, received_at, source. VOID использует null вместо счёта.

Новая запись `decide` запрещена после kickoff и по реальным часам процесса, даже с переданным старым временем. `replay` уже записанного решения доступен на его архивной версии кода. Запись ручного исполнения после матча отмечается RETROSPECTIVE_EXECUTION_RECORD и не становится системной рекомендацией.

Постматчевый review может иметь `category`, `category_evidence`, `premise_observations`. Категории: MODEL_MISS, THRESHOLD_MISS, PRICE_MISS, FACT_MISS, STRUCTURAL_BREAK, GOOD_PASS_BAD_RESULT, BAD_PASS_FALSE_NEGATIVE, NARRATIVE_SUBSTITUTION, MARKET_DIVERGENCE, CORRELATION_EXPOSURE, UNKNOWN. Нужны ссылки на доказательства для любой категории кроме UNKNOWN. Предпосылка: `{premise_id, status: HELD/FAILED/UNKNOWN, evidence: [references]}`; HELD/FAILED требуют ссылок. Это заявление проверяющего, а не независимая проверка содержимого ссылок. Автоматический аудит оставляет качество UNDETERMINED.

Поставщик может выдавать эти файлы автоматически. Сетевой клиент составов и спортивной истории отсутствует; необязательный адаптер котировок 1X2 описан выше. Файлы в data/ исключены из Git.
