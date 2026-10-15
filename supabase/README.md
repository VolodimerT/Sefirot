# Existing private bridge: reviewed delta only

This directory is **not** a clean Supabase bootstrap or a copy of production
migration history. Do not run `db reset` / `db push` against the hosted project.

- `migrations/20261015161027_probe_completion_fence.sql`: CLI-created incremental
  review candidate for the existing PR #22 private queue; installs with claims
  parked. It does not bootstrap tables or activate an API budget.
- `review_only/20261015161311_park_probe_queue.sql`: CLI-created emergency park,
  deliberately outside the forward migration chain. Never auto-apply it as the
  next ordinary migration. It keeps fencing and all records.
- `schema/probe_rollout_manifest.json` in the repository root records paths,
  accepted baseline function-body hashes and canonical probe body identity.

No migration has been applied to the hosted project. The timestamped files were
created with verified official Supabase CLI 2.81.3, not handwritten timestamps.
Local plain PostgreSQL tests do not reconstruct Supabase migration history.
Read `docs/P0_B_ROLLOUT_AND_ROLLBACK_20261015.md` before any separately authorized
operation. A future approved migration becomes immutable after application.
