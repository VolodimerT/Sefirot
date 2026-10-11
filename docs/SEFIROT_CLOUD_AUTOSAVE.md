# SEFIROT private daily cloud archive — runbook v1 (2026-10-11)

This is an **active private Supabase database archive** in the existing `sefirot-core` project. The code is in a separate draft PR. It is not an automatic ChatGPT message listener; the assistant must invoke the connected Supabase tool after each **final daily report**.

## Security model

- Table `sefirot.daily_report_archive`, function `sefirot.save_daily_report(jsonb)`.
- Only an explicitly connected, privileged **Supabase SQL connector** may write/read; no new public Edge endpoint or shared token. RLS on; ALL grants revoked for PUBLIC/anon/authenticated/service_role. The schema is not Data API exposed.
- Append only: report_day + SHA256 primary key; UPDATE/DELETE/TRUNCATE triggers reject modifications. New correction => new hash/version.
- Accepted status strictly `REPORTED_UNVERIFIED`. This is an archive of what the chat reported, **not** the original CORE run, sportsbook receipt, audited bank balance or certified EV.
- No wagers, LIVE, automatic market selection, provider calls or separate credentials.
- Daily report content can include private financial information: NEVER place it in GitHub PR, issue, Actions logs or public code. Cloud storage is subject to Supabase account permissions and platform security.

## Envelope (synthetic illustration)

```json
{
  "schema": "sefirot-daily-report-v1",
  "day": "2030-02-01",
  "timezone": "Europe/Kyiv",
  "origin": "CHAT_DAILY",
  "status": "REPORTED_UNVERIFIED",
  "source_refs": ["SYNTHETIC_TEST_ONLY"],
  "report": "SYNTHETIC_TEST_ONLY: no real tickets or forecasts."
}
```

A verified single-day output of `ticket-audit` can be wrapped with origin `TICKET_AUDIT` and the entire audited object as `report`. The `days` list must contain exactly that Kyiv date; other dates are rejected. Maximum 512,000 bytes of PostgreSQL JSONB text, maximum 100 source refs.

## Every final day-end report, *before* telling the user it was saved

1. Produce one coherent report for a Kyiv calendar date. Preserve original CORE `BET/PASS` or say `SEFIROT_NOT_EXECUTED`; separate Parik24 executions from external Stake/Yaryi suggestions and RESEARCH_ONLY. Don't invent missing tickets; keep CASHOUT/PENDING/VOID and reconciliation discrepancies.
2. Call the connected `Supabase.execute_sql` with `SELECT sefirot.save_daily_report(<report-jsonb>) AS save_receipt;`. **Escape payload safely**; recommended SQL uses `convert_from(decode('<lowercase hex of UTF-8 JSON>','hex'),'UTF8')::jsonb` inside the function call. `scripts/cloud_daily_sql.py --report private/report.json` generates an injection-safe statement with no credentials or network.
3. Check the actual returned JSON `saved:true, backend:PRIVATE_SUPABASE, day, sha256, versions_for_day, new_version`. No returned acknowledgment = NOT_SAVED. If a timeout occurs, query the archive by day and hash first, then safely retry. The function is idempotent.
4. Optionally read back `SELECT payload, sha256 FROM sefirot.daily_report_archive WHERE report_day='YYYY-MM-DD' AND sha256='64-lowercase-hex';` and compare the returned stored hash, day and report. **Never print the private payload to public channels.**
5. Give the user the date, cloud SAVED/NOT_SAVED, SHA256 prefix (not the private report) and version number. A correction creates an additional version without deleting the old one.

## Restore in a new chat

Use the connected Supabase account to fetch index metadata:

```sql
SELECT report_day, sha256, saved_at FROM sefirot.daily_report_archive
ORDER BY saved_at DESC, sha256 DESC LIMIT 10;
```

To retrieve a date:

```sql
SELECT report_day, sha256, saved_at, payload
FROM sefirot.daily_report_archive
WHERE report_day = '2030-02-01'
ORDER BY saved_at DESC, sha256 DESC;
```

Content is personal and must not be copied to the public repo. For development context, additionally read `docs/AI_HANDOFF.md`, #33 and exact GitHub draft PR head/CI; this archive does not track commits.

## Known boundaries

- Cloud SHA256 is `sha256(UTF8(postgres_jsonb::text))`. The existing local autosave hash uses compact sorted Python JSON; **the two hashes are not interchangeable**. Each archive verifies using its own format.
- This does not automatically intercept ChatGPT messages. Cross-chat behavior requires a workflow instruction (see `docs/PROJECT_INSTRUCTIONS_DAILY_SAVE.md`) and Supabase connector availability. If this tool is unavailable, don't claim cloud saving.
- Do not put token material, arbitrary full conversation dumps, private sports source packets or raw screenshots into the archive. It is for explicit **final daily summaries**.
- Test code can be exercised in a transaction that ends with `ROLLBACK`, leaving no synthetic report behind. No cloud data is deployed/merged through public GitHub.
