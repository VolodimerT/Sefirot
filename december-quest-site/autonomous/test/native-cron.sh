#!/usr/bin/env bash
# Disposable upstream PostgreSQL 15, pg_cron and pg_net. No host ports or volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
image=supabase/postgres@sha256:caae3d066f437332d593011e3e7ecf78ab005ce9b89378efd53f97f0410563ad
container=$(docker run -d --rm --network none --user postgres --entrypoint /bin/bash "$image" -c '
  set -e
  initdb -A trust -D /tmp/qa >/dev/null
  exec postgres -D /tmp/qa -k /tmp -c unix_socket_directories=/tmp -c shared_preload_libraries=pg_cron,pg_net -c cron.database_name=postgres -c cron.use_background_workers=on
')
trap 'docker stop "$container" >/dev/null || true' EXIT
query(){ docker exec -i "$container" psql -XAtq -v ON_ERROR_STOP=1 -h /tmp -d postgres "$@"; }
for attempt in {1..30}; do
  if query -c 'select 1' >/dev/null 2>&1; then break; fi
  sleep 1
done
query <<'SQL'
create extension pg_cron;
create extension pg_net;
create role anon; create role authenticated; create role service_role;
create table qa_clock(stamp timestamptz);
insert into qa_clock values('2026-12-01 17:00:00+00');
create function dq_predictor_cycle_start(timestamptz) returns timestamptz language sql as $$select date_trunc('day',$1)$$;
create function dq_predictor_run_state(text) returns jsonb language sql as $$select '{}'::jsonb$$;
select cron.schedule('dq-autonomous-dec2026-19kyiv','0 17 * * *',
  $$select net.http_post('http://127.0.0.1:9/functions/v1/dq-autonomous-predictor-v63','{}'::jsonb)$$);
create table qa_original as select * from cron.job;
SQL
# Advance only the DQ scheduler clock. The cron launcher and pg_net run on real time.
sed 's/stamp timestamptz := statement_timestamp()/stamp timestamptz := (select stamp from public.qa_clock)/' recovery.sql | query
query <recovery-finish.sql
query -c "select cron.alter_job(jobid,schedule:='1 seconds') from cron.job"
for minute in 00 12 24; do
  query -c "update qa_clock set stamp='2026-12-01 17:${minute}:00+00'"
  for attempt in {1..30}; do
    count=$(query -c "select count(*) from dq_predictor_dispatch_slots where minute=$minute")
    if [[ $count == 1 ]]; then break; fi
    sleep 1
  done
  [[ $count == 1 ]]
done
# Port 9 deliberately fails: pg_net must return a transport error for each delivery.
for attempt in {1..30}; do
  count=$(query -c 'select count(*) from net._http_response where error_msg is not null')
  if [[ $count == 3 ]]; then break; fi
  sleep 1
done
[[ $count == 3 ]]
query -c "select cron.alter_job(jobid,schedule:='0,12,24 17 * * *') from cron.job"
query <recovery-rollback.sql
[[ $(query -c 'select count(*) from qa_original o join cron.job j using(jobid) where o.command=j.command and o.schedule=j.schedule and o.active=j.active') == 1 ]]
echo 'PASS native pg_cron, three bounded pg_net attempts during transport outage, exact job rollback'
