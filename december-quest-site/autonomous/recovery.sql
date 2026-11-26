-- Staging only. The existing cron owner's Vault-backed command remains the dispatcher.
begin;
create table public.dq_predictor_dispatch_slots (
  cycle_started_at timestamptz not null,
  minute integer not null check (minute in (0,12,24)),
  primary key (cycle_started_at,minute)
);
revoke all on public.dq_predictor_dispatch_slots from public,anon,authenticated,service_role;

create function public.dq_scheduled_predictor(original_command text)
returns void language plpgsql security invoker as $$
declare
  stamp timestamptz := statement_timestamp();
  utc_time timestamp := stamp at time zone 'UTC';
  slot integer := extract(minute from utc_time);
  cycle timestamptz := public.dq_predictor_cycle_start(stamp);
  target constant text := '/functions/v1/dq-autonomous-predictor-v63';
begin
  if utc_time::date > date '2026-12-31' or extract(hour from utc_time)<>17 or slot not in (0,12,24) then return; end if;
  if public.dq_predictor_run_state('DQ-POISSON-0.3')->>'recent_success_at' is not null then return; end if;
  insert into public.dq_predictor_dispatch_slots values(cycle,slot) on conflict do nothing;
  if not found then return; end if;
  -- Queueing (pg_net) and slot reservation commit or roll back together.
  original_command := replace(original_command,target,target||case when slot=0 then '?run_until=' else '?retry_until=' end||
      floor(extract(epoch from (date_trunc('minute',stamp)+interval '10 minutes'))*1000)::bigint);
  execute original_command;
end;
$$;
revoke all on function public.dq_scheduled_predictor(text) from public,anon,authenticated,service_role;

do $install$
declare
  j record;
begin
  select * into strict j from cron.job where jobname='dq-autonomous-dec2026-19kyiv';
  if not j.active or j.schedule<>'0 17 * * *'
    or j.command not like '%/functions/v1/dq-autonomous-predictor-v63''%'
    or position('$dq_original$' in j.command)>0 then raise exception 'UNEXPECTED_DQ_CRON_CONFIGURATION'; end if;
  if j.username<>current_user then raise exception 'INSTALL_AS_EXISTING_CRON_OWNER'; end if;
  perform cron.alter_job(j.jobid, schedule:='0,12,24 17 * * *',
    command:='select public.dq_scheduled_predictor($dq_original$'||j.command||'$dq_original$)');
end;
$install$;
commit;
