-- Review candidate only. No automatic deployment and no budget activation.
-- CLI-created migration; requires an existing private queue, not an empty DB.
begin;
set local lock_timeout='3s';
set local statement_timeout='15s';
do $$
begin
  if current_user<>'postgres' or pg_catalog.to_regclass('sefirot.chat_bridge_jobs') is null
      or pg_catalog.to_regclass('sefirot_budget_private.sports_budget') is null then
    raise exception 'PROBE_ROLLOUT_PRIVATE_SCHEMA_REQUIRED' using errcode='22023';
  end if;
end $$;
lock table sefirot.chat_bridge_jobs in share row exclusive mode;
lock table sefirot_budget_private.sports_budget in share mode;
do $$
begin
  if exists(select 1 from sefirot.chat_bridge_jobs where status in ('PENDING','RUNNING')) then
    raise exception 'PROBE_ROLLOUT_QUEUE_NOT_DRAINED' using errcode='22023';
  end if;
  if (select count(*) from sefirot_budget_private.sports_budget where singleton=true)<>1
      or not exists(select 1 from sefirot_budget_private.sports_budget
                    where singleton=true and enabled=false and in_flight is null) then
    raise exception 'PROBE_ROLLOUT_BUDGET_NOT_QUIESCENT' using errcode='22023';
  end if;
  if not (select relrowsecurity from pg_catalog.pg_class where oid='sefirot.chat_bridge_jobs'::regclass)
      or pg_catalog.has_schema_privilege('service_role','sefirot','USAGE')
      or pg_catalog.has_table_privilege('service_role','sefirot.chat_bridge_jobs','SELECT,INSERT,UPDATE,DELETE')
      or pg_catalog.has_table_privilege('anon','sefirot.chat_bridge_jobs','SELECT,INSERT,UPDATE,DELETE')
      or pg_catalog.has_table_privilege('authenticated','sefirot.chat_bridge_jobs','SELECT,INSERT,UPDATE,DELETE') then
    raise exception 'PROBE_ROLLOUT_QUEUE_ACCESS_DRIFT' using errcode='22023';
  end if;
  if pg_catalog.to_regprocedure('public.sefirot_chat_claim()') is null
      or pg_catalog.to_regprocedure('public.sefirot_chat_complete(uuid,boolean,jsonb,text)') is null then
    raise exception 'PROBE_ROLLOUT_BRIDGE_REQUIRED' using errcode='22023';
  end if;
  if pg_catalog.has_function_privilege('anon','public.sefirot_chat_claim()','EXECUTE')
      or pg_catalog.has_function_privilege('authenticated','public.sefirot_chat_claim()','EXECUTE') then
    raise exception 'PROBE_ROLLOUT_CLAIM_ACCESS_DRIFT' using errcode='22023';
  end if;
end $$;
do $$
begin
  if not exists(select 1 from pg_catalog.pg_proc p
      where p.oid=pg_catalog.to_regprocedure('public.sefirot_chat_complete(uuid,boolean,jsonb,text)')
        and pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')='9e377e91bf3cedd04f2a3f65924041fe0a8b7752f363d3d0d50167d278186fab') then
    raise exception 'PROBE_PARK_FENCE_REQUIRED' using errcode='22023';
  end if;
end $$;
-- Safe park: keep fencing and receipts, disable machine claims/completion.
revoke execute on function public.sefirot_chat_claim() from service_role;
revoke execute on function public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text) from service_role;
do $$ begin
  if pg_catalog.has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE')
      or pg_catalog.has_function_privilege('service_role','public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','EXECUTE') then
    raise exception 'PROBE_PARK_INHERITED_ACCESS_DRIFT' using errcode='22023';
  end if;
end $$;
notify pgrst, 'reload schema';
commit;
