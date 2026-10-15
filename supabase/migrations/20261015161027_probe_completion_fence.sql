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
  if (select count(*) from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname='sefirot_chat_complete')<>1
      or (select count(*) from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname='sefirot_probe_complete')>1
      or pg_catalog.to_regprocedure('public.sefirot_chat_claim()') is null
      or pg_catalog.to_regprocedure('public.sefirot_chat_complete(uuid,boolean,jsonb,text)') is null then
    raise exception 'PROBE_ROLLOUT_BRIDGE_REQUIRED' using errcode='22023';
  end if;
  if pg_catalog.has_function_privilege('anon','public.sefirot_chat_claim()','EXECUTE')
      or pg_catalog.has_function_privilege('authenticated','public.sefirot_chat_claim()','EXECUTE') then
    raise exception 'PROBE_ROLLOUT_CLAIM_ACCESS_DRIFT' using errcode='22023';
  end if;
end $$;
do $$
declare old_body text; old_hash text; saved record; current_fn record;
begin
  select p.*, l.lanname into current_fn from pg_catalog.pg_proc p
    join pg_catalog.pg_language l on l.oid=p.prolang
    where p.oid='public.sefirot_chat_complete(uuid,boolean,jsonb,text)'::regprocedure;
  old_body=current_fn.prosrc;
  old_hash=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(old_body,'UTF8')),'hex');
  if current_fn.proowner<>'postgres'::regrole or not current_fn.prosecdef
      or current_fn.proisstrict or current_fn.proretset or current_fn.pronargdefaults<>0
      or current_fn.lanname<>'plpgsql' or current_fn.prorettype<>'jsonb'::regtype
      or current_fn.proconfig is distinct from array['search_path=""']
      or current_fn.proargnames is distinct from array['p_id','p_success','p_response','p_error']
      or old_hash not in ('ea4ffb3167bea44c83d5af1c088699debb92e0a4ab1570828e153f81bc4663f0','6d88b7f710d90b9f4cb7852fd57b1b02044b0f8fb52b6a75bc664801a43bc68b','02b68217bddbe0cb3bf54069f063c6e2ae6f2693cdf4b581e184ef0b30b29ad6','4df3982c504c8eafc7f1c95b615e02e3d907043325ca97939f9f95d9845b9d12','9e377e91bf3cedd04f2a3f65924041fe0a8b7752f363d3d0d50167d278186fab')
      or exists(select 1 from pg_catalog.aclexplode(coalesce(current_fn.proacl,
               pg_catalog.acldefault('f',current_fn.proowner))) a
                where a.grantee not in ('postgres'::regrole,'service_role'::regrole)) then
    raise exception 'PROBE_ROLLOUT_COMPLETION_DRIFT' using errcode='22023';
  end if;
  if pg_catalog.to_regprocedure('public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)') is not null
      and not exists(select 1 from pg_catalog.pg_proc p
        where p.oid=pg_catalog.to_regprocedure('public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)')
          and p.proowner='postgres'::regrole and p.prosecdef
          and p.proconfig=array['search_path=""']
          and p.prorettype='jsonb'::regtype
          and p.proargnames=array['p_id','p_attempt','p_success','p_response','p_error']
          and not exists(select 1 from pg_catalog.aclexplode(coalesce(p.proacl,
               pg_catalog.acldefault('f',p.proowner))) a
                where a.grantee not in ('postgres'::regrole,'service_role'::regrole))
          and pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')='6e938616a18fec26c8e6ccefdb6f4abfa34f5c44deaf89a66dd40b02478c14c4') then
    raise exception 'PROBE_ROLLOUT_RPC_DRIFT' using errcode='22023';
  end if;
  if pg_catalog.to_regprocedure('sefirot.chat_complete_before_probe_fence(uuid,boolean,jsonb,text)') is null then
    if old_hash='9e377e91bf3cedd04f2a3f65924041fe0a8b7752f363d3d0d50167d278186fab' then
      raise exception 'PROBE_ROLLOUT_BACKUP_REQUIRED' using errcode='22023';
    end if;
    execute pg_catalog.format($ddl$
      create function sefirot.chat_complete_before_probe_fence(p_id uuid,p_success boolean,p_response jsonb,p_error text)
      returns jsonb language plpgsql security definer set search_path='' as %L
    $ddl$,old_body);
  else
    select * into saved from pg_catalog.pg_proc
      where oid='sefirot.chat_complete_before_probe_fence(uuid,boolean,jsonb,text)'::regprocedure;
    if old_hash<>'9e377e91bf3cedd04f2a3f65924041fe0a8b7752f363d3d0d50167d278186fab' or saved.proowner<>'postgres'::regrole or not saved.prosecdef
        or saved.proconfig is distinct from array['search_path=""']
        or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(saved.prosrc,'UTF8')),'hex') not in ('ea4ffb3167bea44c83d5af1c088699debb92e0a4ab1570828e153f81bc4663f0','6d88b7f710d90b9f4cb7852fd57b1b02044b0f8fb52b6a75bc664801a43bc68b','02b68217bddbe0cb3bf54069f063c6e2ae6f2693cdf4b581e184ef0b30b29ad6','4df3982c504c8eafc7f1c95b615e02e3d907043325ca97939f9f95d9845b9d12')
        or exists(select 1 from pg_catalog.aclexplode(coalesce(saved.proacl,
               pg_catalog.acldefault('f',saved.proowner))) a where a.grantee<>'postgres'::regrole) then
      raise exception 'PROBE_ROLLOUT_BACKUP_DRIFT' using errcode='22023';
    end if;
  end if;
end $$;
revoke all on function sefirot.chat_complete_before_probe_fence(uuid,boolean,jsonb,text)
  from public,anon,authenticated,service_role;
create or replace function public.sefirot_probe_complete(p_id uuid, p_attempt integer,
    p_success boolean, p_response jsonb, p_error text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item record; query_count integer; i integer; q jsonb; expected jsonb;
begin
  select kind,status,attempts,request,response,error into item
    from sefirot.chat_bridge_jobs where id=p_id for update;
  if not found or item.kind<>'sports_probe' or p_attempt is null
      or p_attempt not between 1 and 3 or item.attempts<>p_attempt
      or p_success is null then
    raise exception 'STALE_PROBE_LEASE' using errcode='22023';
  end if;
  if (p_success and (p_attempt<>1 or p_error is not null or p_response is null
       or pg_catalog.jsonb_typeof(p_response)<>'object'
       or p_response->>'stage' is distinct from 'SPORTS_API_PROBE'
       or p_response->>'provider' is distinct from 'API_FOOTBALL_V3'
       or p_response->>'mode' is distinct from 'RESEARCH_ONLY'
       or p_response->'monetary_permission' is distinct from 'false'::jsonb
       or p_response->'execution_enabled' is distinct from 'false'::jsonb
       or p_response->'automatic_execution' is distinct from 'false'::jsonb
       or p_response->'model_calibrated' is distinct from 'false'::jsonb
       or p_response->'shared_budget_required' is distinct from 'true'::jsonb
       or pg_catalog.jsonb_typeof(p_response->'queries') is distinct from 'array'
       or pg_catalog.jsonb_typeof(item.request->'queries') is distinct from 'array'))
      or (not p_success and (p_response is not null or p_error is null
       or p_error not in ('INPUT_VALIDATION_OR_PREMATCH_GATE','RESEARCH_RUNNER_ERROR',
                         'PROVIDER_FETCH_LEASE_REQUIRED','PROVIDER_FETCH_RETRY_REQUIRES_REVIEW')))
      or pg_catalog.octet_length(p_response::text)>900000 or pg_catalog.length(p_error)>300 then
    raise exception 'INVALID_PROBE_RESPONSE' using errcode='22023';
  end if;
  if p_success then
    query_count=pg_catalog.jsonb_array_length(p_response->'queries');
    if query_count not between 1 and 8
        or pg_catalog.jsonb_array_length(item.request->'queries') not between 1 and 8
        or query_count>pg_catalog.jsonb_array_length(item.request->'queries') then
      raise exception 'INVALID_PROBE_RESPONSE' using errcode='22023';
    end if;
    for i in 0..query_count-1 loop
      q=p_response->'queries'->i; expected=item.request->'queries'->i;
      if pg_catalog.jsonb_typeof(q) is distinct from 'object'
          or q->>'endpoint' is null or q->>'endpoint' not in
              ('status','fixtures','fixtures/statistics','fixtures/lineups')
          or q->'endpoint' is distinct from expected->'endpoint'
          or pg_catalog.jsonb_typeof(q->'params') is distinct from 'object'
          or q->'params' is distinct from expected->'params'
          or q->>'status' is null or q->>'status' not in ('DONE','ERROR')
          or (q->>'status'='ERROR' and i<>query_count-1) then
        raise exception 'INVALID_PROBE_RESPONSE' using errcode='22023';
      end if;
    end loop;
    if query_count<pg_catalog.jsonb_array_length(item.request->'queries')
        and p_response->'queries'->(query_count-1)->>'status'<>'ERROR' then
      raise exception 'INVALID_PROBE_RESPONSE' using errcode='22023';
    end if;
  end if;
  if item.status in ('DONE','ERROR') and item.response is not distinct from p_response
      and item.error is not distinct from p_error
      and item.status=(case when p_success then 'DONE' else 'ERROR' end) then
    return pg_catalog.jsonb_build_object('completed',true,'id',p_id,'attempts',p_attempt);
  end if;
  if item.status<>'RUNNING' then
    raise exception 'INVALID_PROBE_JOB_STATE' using errcode='22023';
  end if;
  update sefirot.chat_bridge_jobs
    set status=case when p_success then 'DONE' else 'ERROR' end,
        completed_at=pg_catalog.now(),response=p_response,error=p_error where id=p_id;
  return pg_catalog.jsonb_build_object('completed',true,'id',p_id,'attempts',p_attempt);
end $$;

create or replace function public.sefirot_chat_complete(p_id uuid, p_success boolean,
    p_response jsonb, p_error text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare job_kind text;
begin
  select kind into job_kind from sefirot.chat_bridge_jobs where id=p_id for update;
  if job_kind='sports_probe' then
    raise exception 'PROBE_LEASE_REQUIRED' using errcode='22023';
  end if;
  if job_kind='situation' then
    raise exception 'SITUATION_LEASE_REQUIRED' using errcode='22023';
  end if;
  return sefirot.chat_complete_before_probe_fence(p_id,p_success,p_response,p_error);
end $$;
revoke all on function public.sefirot_chat_complete(uuid,boolean,jsonb,text) from public,anon,authenticated;
revoke all on function public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text) from public,anon,authenticated;
grant execute on function public.sefirot_chat_complete(uuid,boolean,jsonb,text) to service_role;
grant execute on function public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text) to service_role;
-- Always install parked: no mixed-version worker can claim after this commit.
revoke execute on function public.sefirot_chat_claim() from service_role;
do $$ begin
  if pg_catalog.has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE') then
    raise exception 'PROBE_ROLLOUT_INHERITED_CLAIM_ACCESS' using errcode='22023';
  end if;
end $$;
notify pgrst, 'reload schema';
commit;
