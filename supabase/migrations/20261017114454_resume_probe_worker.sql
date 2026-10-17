-- Explicit worker recovery only. Deploy and verify the fenced sports-only
-- worker first, wait for the legacy instance to retire, then apply as postgres.
-- Does not activate, renew, reset, reserve, or otherwise modify API budget.
begin;
set local lock_timeout='3s';
set local statement_timeout='15s';
do $$ begin
  if current_user<>'postgres'
      or pg_catalog.to_regclass('sefirot.chat_bridge_jobs') is null
      or pg_catalog.to_regclass('sefirot_budget_private.sports_budget') is null then
    raise exception 'PROBE_RESUME_PRIVATE_SCHEMA_REQUIRED' using errcode='22023';
  end if;
end $$;
lock table sefirot.chat_bridge_jobs in share row exclusive mode;
lock table sefirot_budget_private.sports_budget in share mode;
do $$
declare item record; fingerprint text;
begin
  if exists(select 1 from sefirot.chat_bridge_jobs where status='RUNNING'
      or status='PENDING' and (kind<>'sports_probe' or attempts<>0)) then
    raise exception 'PROBE_RESUME_QUEUE_REVIEW_REQUIRED' using errcode='22023';
  end if;
  if (select count(*) from sefirot_budget_private.sports_budget where singleton)<>1
      or exists(select 1 from sefirot_budget_private.sports_budget where in_flight is not null) then
    raise exception 'PROBE_RESUME_IN_FLIGHT_BUDGET' using errcode='22023';
  end if;
  if not (select relrowsecurity from pg_catalog.pg_class
          where oid='sefirot.chat_bridge_jobs'::regclass)
      or pg_catalog.has_schema_privilege('anon','sefirot','USAGE')
      or pg_catalog.has_schema_privilege('authenticated','sefirot','USAGE')
      or pg_catalog.has_schema_privilege('service_role','sefirot','USAGE') then
    raise exception 'PROBE_RESUME_PRIVATE_ACCESS_DRIFT' using errcode='22023';
  end if;
  for item in select * from (values
      ('public.sefirot_chat_claim()',array['97d93a6de4f246660565569edc2c46c214e1cfa615114a5852df075a98fcd25e','4bb9eee8436f42e018766c6927aacaa00def6f59a856664f7a9054e9cf45f267']),
      ('public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)',array['6e938616a18fec26c8e6ccefdb6f4abfa34f5c44deaf89a66dd40b02478c14c4']),
      ('public.sefirot_chat_complete(uuid,boolean,jsonb,text)',array['9e377e91bf3cedd04f2a3f65924041fe0a8b7752f363d3d0d50167d278186fab'])
    ) expected(signature,hashes) loop
    select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')
      into fingerprint from pg_catalog.pg_proc p
      where p.oid=pg_catalog.to_regprocedure(item.signature)
        and p.proowner='postgres'::regrole and p.prosecdef
        and p.proconfig=array['search_path=""'];
    if fingerprint is null or not fingerprint=any(item.hashes) then
      raise exception 'PROBE_RESUME_FUNCTION_DRIFT' using errcode='22023';
    end if;
    if exists(select 1 from pg_catalog.pg_proc p
        cross join lateral pg_catalog.aclexplode(coalesce(p.proacl,
            pg_catalog.acldefault('f',p.proowner))) a
        where p.oid=pg_catalog.to_regprocedure(item.signature)
          and (a.grantee not in ('postgres'::regrole,'service_role'::regrole)
               or a.grantee='service_role'::regrole and a.is_grantable))
        or pg_catalog.has_function_privilege('anon',item.signature,'EXECUTE')
        or pg_catalog.has_function_privilege('authenticated',item.signature,'EXECUTE') then
      raise exception 'PROBE_RESUME_FUNCTION_ACCESS_DRIFT' using errcode='22023';
    end if;
  end loop;
end $$;
grant execute on function public.sefirot_chat_claim() to service_role;
grant execute on function public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text) to service_role;
notify pgrst, 'reload schema';
commit;
