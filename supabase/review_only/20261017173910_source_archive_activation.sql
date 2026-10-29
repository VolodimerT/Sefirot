-- REVIEW ONLY. Owner approval and matched SQL/relay/gateway/worker releases required.
-- Run with no queued/running jobs and protected budget disabled/no in-flight call.
-- No budget grant/update, source backfill, cron creation or provider call here.
begin;
set local lock_timeout='3s';
lock table sefirot.chat_bridge_jobs in share row exclusive mode;
do $$ begin
 if current_user<>'postgres'
  or exists(select 1 from sefirot.chat_bridge_jobs where status in ('PENDING','RUNNING'))
  or not exists(select 1 from sefirot_budget_private.sports_budget where singleton and not enabled and in_flight is null)
 then raise exception 'SOURCE_ACTIVATION_QUIESCENT_OWNER_REQUIRED';end if;
end $$;
grant execute on function public.sefirot_source_begin(uuid,integer,text,jsonb),public.sefirot_source_append(text,text,uuid,integer),
 public.sefirot_source_export(text) to service_role;
notify pgrst,'reload schema';
commit;
