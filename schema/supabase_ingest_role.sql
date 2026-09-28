-- Apply to an existing SEFIROT private schema once. This creates a disabled
-- (NOLOGIN), least-privilege ingestion identity. Credentials are provisioned
-- separately by the owner and must never be put in a migration or Git.
create role sefirot_ingest nologin noinherit nosuperuser nocreatedb
  nocreaterole noreplication nobypassrls;
grant connect on database postgres to sefirot_ingest;
grant usage on schema sefirot to sefirot_ingest;

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
    execute format('grant select, insert on sefirot.%I to sefirot_ingest', table_name);
    execute format('create policy ingest_read on sefirot.%I for select to sefirot_ingest using (true)', table_name);
    execute format('create policy ingest_append on sefirot.%I for insert to sefirot_ingest with check (true)', table_name);
  end loop;
end;
$$;

-- UPDATE/DELETE remain blocked by privileges and immutable ledger triggers.
-- anon, authenticated and service_role retain zero privileges on this schema.
