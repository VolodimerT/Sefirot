# Контракт локальных данных

Формат `examples/core2_case.json` содержит раздельные sports / markets / quotes / recheck / result. Для рабочего CLI сохраните эти поля в отдельные файлы: котировки загружаются после capture.

- Везде ISO 8601 с часовым поясом. naive timestamp запрещён.
- `match`: стабильные ID матча/команд, лига, kickoff, `sport=football`, `format=REGULATION_90`.
- `as_of`: срез доступного спортивного знания, не будущее по локальным часам.
- `sources`: ID, группа независимости, reliability 0..1, enabled. Это оценка поставщика, а не автоматическая гарантия достоверности.
- `evidence`: ID/key/value, FACT/INFERENCE/ASSUMPTION, source_id, observed_at ≤ published_at ≤ received_at ≤ as_of, critical, supports. Supports ссылаются на ранее доступные FACT; циклы запрещены.
- Обязательные ключи: home_team, away_team, format, lineup, injuries, coach, rotation, tactics. Lineup содержит status CONFIRMED и уникальные 11 ID игроков с каждой стороны. Травмы — списки для home/away. Tactics: home_style, away_style, fit SUPPORTED, key_factor. Изменения этих фактов требуют нового seal.
- `history`: id/home/away/league, kickoff < finished_at ≤ received_at, целый неотрицательный счёт, source_id. Недоступные на as_of результаты исключаются. Целевой матч запрещён в истории.
- `markets`: 1–7 кандидатов, по одному на семейство, объявленных без цены.
- `quotes`: market, bookmaker, decimal odds >1, observed_at ≤ received_at, phase OPEN/FINAL/ENTRY/CLOSE, rules REGULATION_90. OPEN/FINAL/ENTRY входят после seal. CLOSE — только постматчевый аудит. `line_id` связывает полную 1X2 линию.
- `recheck`: checked_at и новый полный набор evidence. Простого поля «проверено=true» недостаточно.
- `result`: match_id, FINISHED/VOID, home_goals/away_goals, finished_at, received_at, source. VOID использует null вместо счёта.

Поставщик может выдавать эти файлы автоматически. В этой сборке нет сетевого клиента, который самостоятельно собирает составы и котировки. Файлы не публикуются в Git, если лежат в data/.
