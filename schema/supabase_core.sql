-- SEFIROT CORE 2.1 private PostgreSQL mirror of the SQLite ledger.
-- This file describes the verified cloud schema and is for FRESH databases.
-- Existing project kxqpwgwihtjmqlcxgfxp used two migrations; do not rerun
-- these CREATE TABLE statements against it.
-- No client role can read or write these tables; use a controlled server-side
-- migration/export process with a private database connection.

create schema if not exists sefirot;
revoke all on schema sefirot from public, anon, authenticated, service_role;

create table sefirot.teams (
  id text primary key, payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.markets (
  id text primary key, payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.model_versions (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.matches (
  id text primary key, home text not null references sefirot.teams(id),
  away text not null references sefirot.teams(id), kickoff timestamptz not null,
  league text not null, payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  check (home <> away)
);
create table sefirot.predictions (
  id text primary key, match_id text not null references sefirot.matches(id),
  model_id text not null references sefirot.model_versions(id), at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.decisions (
  id text primary key, prediction_id text not null references sefirot.predictions(id),
  at timestamptz not null, payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.odds_snapshots (
  id text primary key, prediction_id text not null references sefirot.predictions(id),
  market_id text not null references sefirot.markets(id), at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.bets (
  id text primary key, decision_id text not null references sefirot.decisions(id),
  at timestamptz not null, payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.results (
  id text primary key references sefirot.matches(id), at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.closing_odds (
  id text primary key, match_id text not null references sefirot.matches(id),
  market_id text not null references sefirot.markets(id), at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.calibration_history (
  id text primary key, prediction_id text not null references sefirot.predictions(id),
  market_id text not null references sefirot.markets(id), at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  unique (prediction_id, market_id)
);
create table sefirot.postmatch_reports (
  id text primary key, decision_id text not null references sefirot.decisions(id),
  at timestamptz not null, payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.postmortems (
  id text primary key, decision_id text not null references sefirot.decisions(id),
  at timestamptz not null, payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.health_events (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.calibrators (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.validation_runs (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.split_assignments (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.overrides (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.model_routes (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.policy_approvals (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.jobs (
  id text primary key, at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
create table sefirot.audit_logs (
  id bigint primary key, at timestamptz not null, at_source text not null,
  event text not null, payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  payload_source text not null, previous_hash text not null, hash text not null unique,
  check (length(previous_hash) = 64 and length(hash) = 64)
);

create index sefirot_predictions_match on sefirot.predictions (match_id, at);
create index sefirot_decisions_prediction on sefirot.decisions (prediction_id, at);
create index sefirot_odds_prediction on sefirot.odds_snapshots (prediction_id, at);
create index sefirot_metrics_prediction on sefirot.calibration_history (prediction_id, at);
create index sefirot_closing_match on sefirot.closing_odds (match_id, at);
create index sefirot_bets_decision on sefirot.bets (decision_id);
create index sefirot_calibration_market on sefirot.calibration_history (market_id);
create index sefirot_closing_market on sefirot.closing_odds (market_id);
create index sefirot_matches_away on sefirot.matches (away);
create index sefirot_matches_home on sefirot.matches (home);
create index sefirot_odds_market on sefirot.odds_snapshots (market_id);
create index sefirot_postmatch_decision on sefirot.postmatch_reports (decision_id);
create index sefirot_postmortems_decision on sefirot.postmortems (decision_id);
create index sefirot_predictions_model on sefirot.predictions (model_id);

create function sefirot.reject_mutation() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  raise exception 'immutable SEFIROT ledger: update/delete blocked';
end;
$$;
revoke all on function sefirot.reject_mutation() from public, anon, authenticated, service_role;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'teams','matches','markets','odds_snapshots','predictions','bets','results',
    'closing_odds','calibration_history','model_versions','audit_logs',
    'decisions','postmortems','health_events','calibrators','validation_runs',
    'split_assignments','overrides','policy_approvals','model_routes',
    'postmatch_reports','jobs'
  ] loop
    execute format('alter table sefirot.%I enable row level security', table_name);
    execute format('create trigger reject_mutation before update or delete on sefirot.%I '
                   'for each row execute function sefirot.reject_mutation()', table_name);
  end loop;
end;
$$;

revoke all on all tables in schema sefirot from public, anon, authenticated, service_role;
alter default privileges in schema sefirot revoke all on tables from public, anon, authenticated, service_role;
alter default privileges in schema sefirot revoke execute on functions from public, anon, authenticated, service_role;
comment on schema sefirot is 'Private append-only SEFIROT mirror; SQLite remains the authoritative offline ledger.';

-- For the optional SQLite mirror, apply supabase_ingest_role.sql only after
-- reviewing access. Its login is disabled until the owner provisions a secret.
