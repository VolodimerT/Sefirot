-- P1 reviewable bridge-only extension. NOT applied to the deployed project.
-- Requires PR #22 chat_bridge_jobs and its original claim/complete RPCs.
-- No canonical table, snapshot or historical prediction is changed.
begin;

do $$ begin
  if pg_catalog.to_regprocedure('public.sefirot_chat_complete(uuid,boolean,jsonb,text)') is null then
    raise exception 'PR22_BRIDGE_SCHEMA_REQUIRED';
  end if;
end $$;

alter table sefirot.chat_bridge_jobs drop constraint chat_bridge_jobs_kind_check;
alter table sefirot.chat_bridge_jobs add constraint chat_bridge_jobs_kind_check
  check (kind in ('status','demo','capture','decide','result','report','situation'));

create table sefirot.chat_situation_receipts (
  receipt_id text primary key check (receipt_id ~ '^[0-9a-f]{64}$'),
  envelope jsonb not null check (jsonb_typeof(envelope)='object'
                               and octet_length(envelope::text)<=65536),
  registered_at timestamptz not null default now()
);
alter table sefirot.chat_situation_receipts enable row level security;
revoke all on sefirot.chat_situation_receipts from public, anon, authenticated, service_role;

create function sefirot.situation_receipt_append_only() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  raise exception 'STATUS_RECEIPTS_APPEND_ONLY' using errcode='22023';
end $$;
revoke all on function sefirot.situation_receipt_append_only() from public, anon, authenticated, service_role;
create trigger situation_receipt_immutable before update or delete on sefirot.chat_situation_receipts
  for each row execute function sefirot.situation_receipt_append_only();

-- Existing private schema is inaccessible to service_role; narrow definer RPCs
-- are intentional. No anon/authenticated grant, dynamic SQL or user metadata.
create function public.sefirot_situation_source(p_receipt_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare value jsonb;
begin
  if p_receipt_id is null or p_receipt_id !~ '^[0-9a-f]{64}$' then
    raise exception 'INVALID_STATUS_RECEIPT_ID' using errcode='22023';
  end if;
  select envelope into value from sefirot.chat_situation_receipts where receipt_id=p_receipt_id;
  return pg_catalog.jsonb_build_object('receipt',value);
end $$;

create function public.sefirot_situation_enqueue(p_request jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare key_hash text; job_id uuid; existing record; inserted integer;
begin
  if p_request is null or pg_catalog.jsonb_typeof(p_request)<>'object'
      or pg_catalog.octet_length(p_request::text)>16384 then
    raise exception 'INVALID_SITUATION_REQUEST' using errcode='22023';
  end if;
  if array(select pg_catalog.jsonb_object_keys(p_request) order by 1) <>
       array['depth','fixture_id','identity','intent','kickoff','original_provider_receipt_id',
             'provider_status','request_at','status_observed_at']
      or pg_catalog.jsonb_typeof(p_request->'identity')<>'object' then
    raise exception 'INVALID_SITUATION_REQUEST' using errcode='22023';
  end if;
  if array(select pg_catalog.jsonb_object_keys(p_request->'identity') order by 1) <>
       array['model_hash','receipt_hash','source_id','source_revision']
      or (p_request->>'fixture_id') !~ '^[A-Za-z0-9:_./-]{1,128}$'
      or (p_request->>'provider_status') !~ '^[A-Z0-9_]{1,16}$'
      or (p_request->>'original_provider_receipt_id') !~ '^[0-9a-f]{64}$'
      or p_request->>'intent' not in ('auto','prematch','live')
      or p_request->>'depth' not in ('auto','fast','deep')
      or (p_request->'identity'->>'source_id') !~ '^[A-Za-z0-9:_./-]{1,128}$'
      or (p_request->'identity'->>'model_hash') !~ '^[0-9a-f]{64}$'
      or pg_catalog.jsonb_typeof(p_request->'identity'->'source_revision')<>'number'
      or (p_request->'identity'->>'source_revision') !~ '^[0-9]{1,10}$'
      or (p_request->'identity'->>'source_revision')::bigint > 2147483647
      or (p_request->'identity'->>'receipt_hash') is distinct from p_request->>'original_provider_receipt_id'
      or (p_request->>'kickoff') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      or (p_request->>'status_observed_at') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      or (p_request->>'request_at') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      or exists (select 1 from pg_catalog.jsonb_each(p_request) v
                 where v.key<>'identity' and pg_catalog.jsonb_typeof(v.value)<>'string')
      or exists (select 1 from pg_catalog.jsonb_each(p_request->'identity') v
                 where v.key<>'source_revision' and pg_catalog.jsonb_typeof(v.value)<>'string') then
    raise exception 'INVALID_SITUATION_REQUEST' using errcode='22023';
  end if;
  -- Cast validates actual calendar values, not only timezone suffixes.
  perform (p_request->>'kickoff')::timestamptz,
          (p_request->>'status_observed_at')::timestamptz, (p_request->>'request_at')::timestamptz;
  -- Equivalent offsets address one job. The original source envelope is never
  -- normalized/re-signed; only the caller's timestamp assertions are normalized.
  p_request=p_request || pg_catalog.jsonb_build_object(
    'kickoff',pg_catalog.regexp_replace(pg_catalog.to_char(
      (p_request->>'kickoff')::timestamptz at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),'\.000000$','')||'+00:00',
    'status_observed_at',pg_catalog.regexp_replace(pg_catalog.to_char(
      (p_request->>'status_observed_at')::timestamptz at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),'\.000000$','')||'+00:00',
    'request_at',pg_catalog.regexp_replace(pg_catalog.to_char(
      (p_request->>'request_at')::timestamptz at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),'\.000000$','')||'+00:00');
  key_hash=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_request::text,'UTF8')),'hex');
  job_id=pg_catalog.substr(key_hash,1,32)::uuid;
  insert into sefirot.chat_bridge_jobs(id,kind,request) values(job_id,'situation',p_request)
    on conflict (id) do nothing;
  get diagnostics inserted=row_count;
  select kind,request,status into existing from sefirot.chat_bridge_jobs where id=job_id;
  if existing.kind<>'situation' or existing.request is distinct from p_request then
    raise exception 'SITUATION_IDENTITY_COLLISION' using errcode='22023';
  end if;
  return pg_catalog.jsonb_build_object('job_id',job_id,'request_key',key_hash,
                                     'reused',inserted=0,'status',existing.status);
end $$;

create function public.sefirot_situation_complete(p_id uuid, p_attempt integer,
    p_success boolean, p_response jsonb, p_error text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item record;
begin
  select kind,status,attempts,request,response,error into item
    from sefirot.chat_bridge_jobs where id=p_id for update;
  if not found or item.kind<>'situation' or p_attempt is null
      or item.attempts<>p_attempt or p_attempt not between 1 and 3
      or p_success is null then
    raise exception 'STALE_SITUATION_LEASE' using errcode='22023';
  end if;
  if (p_success and (p_response is null or pg_catalog.jsonb_typeof(p_response)<>'object'
       or p_response->>'schema' is distinct from 'sefirot-situation-status-v1'
       or p_response->>'fixture_id' is distinct from item.request->>'fixture_id'
       or p_response->>'original_provider_receipt_id' is distinct from item.request->>'original_provider_receipt_id'
       or p_response->'monetary_permission' is distinct from 'false'::jsonb
       or p_response->'core_invoked' is distinct from 'false'::jsonb
       or p_response->'execution_enabled' is distinct from 'false'::jsonb))
      or (not p_success and (p_response is not null or p_error is null))
      or pg_catalog.octet_length(p_response::text)>900000 or pg_catalog.length(p_error)>300 then
    raise exception 'INVALID_SITUATION_RESPONSE' using errcode='22023';
  end if;
  if item.status in ('DONE','ERROR') and item.response is not distinct from p_response
      and item.error is not distinct from p_error
      and item.status=(case when p_success then 'DONE' else 'ERROR' end) then
    return pg_catalog.jsonb_build_object('completed',true,'id',p_id,'attempts',p_attempt);
  end if;
  if item.status<>'RUNNING' then
    raise exception 'INVALID_SITUATION_JOB_STATE' using errcode='22023';
  end if;
  update sefirot.chat_bridge_jobs set status=case when p_success then 'DONE' else 'ERROR' end,
    completed_at=pg_catalog.now(),response=p_response,error=p_error where id=p_id;
  return pg_catalog.jsonb_build_object('completed',true,'id',p_id,'attempts',p_attempt);
end $$;

-- Preserve the legacy transport for six old kinds; it cannot bypass a
-- situation lease. This is the deployed PR #22 body plus this one guard.
create or replace function public.sefirot_chat_complete(p_id uuid, p_success boolean,
    p_response jsonb, p_error text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item record;
begin
  select kind,status,attempts into item from sefirot.chat_bridge_jobs where id=p_id for update;
  if not found or item.status<>'RUNNING' then
    raise exception 'INVALID_BRIDGE_JOB_STATE' using errcode='22023';
  end if;
  if item.kind='situation' then
    raise exception 'SITUATION_LEASE_REQUIRED' using errcode='22023';
  end if;
  if (p_response is not null and pg_catalog.octet_length(p_response::text)>900000)
      or (p_error is not null and pg_catalog.length(p_error)>300) then
    raise exception 'INVALID_BRIDGE_JOB_RESULT_SIZE' using errcode='22023';
  end if;
  update sefirot.chat_bridge_jobs
    set status=case when p_success then 'DONE' else 'ERROR' end,
        completed_at=pg_catalog.now(),response=p_response,error=p_error where id=p_id;
  return pg_catalog.jsonb_build_object('completed',true,'id',p_id,'attempts',item.attempts);
end $$;

revoke all on function public.sefirot_situation_source(text) from public, anon, authenticated;
revoke all on function public.sefirot_situation_enqueue(jsonb) from public, anon, authenticated;
revoke all on function public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) from public, anon, authenticated;
grant execute on function public.sefirot_situation_source(text) to service_role;
grant execute on function public.sefirot_situation_enqueue(jsonb) to service_role;
grant execute on function public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) to service_role;
commit;
