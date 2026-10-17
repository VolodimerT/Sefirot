-- Review-only populated upgrade. No hosted deployment or queue activation.
-- Run only after probe completion fence AND safe park; preserve existing rows.
-- Rollback is continued parking: retain these receipts/RPCs and both fences.
begin;
set local lock_timeout='3s';
set local statement_timeout='15s';
do $$ begin
  if current_user<>'postgres'
      or pg_catalog.to_regclass('sefirot.chat_bridge_jobs') is null
      or pg_catalog.to_regclass('sefirot_budget_private.sports_budget') is null then
    raise exception 'SITUATION_ROLLOUT_PRIVATE_SCHEMA_REQUIRED' using errcode='22023';
  end if;
end $$;
lock table sefirot.chat_bridge_jobs in share row exclusive mode;
lock table sefirot_budget_private.sports_budget in share mode;
do $$
declare f record; expected record; actual_kind text; object_count integer;
begin
  if exists(select 1 from sefirot.chat_bridge_jobs where status in ('PENDING','RUNNING')) then
    raise exception 'SITUATION_ROLLOUT_QUEUE_NOT_DRAINED' using errcode='22023';
  end if;
  if (select count(*) from sefirot_budget_private.sports_budget where singleton=true)<>1
      or not exists(select 1 from sefirot_budget_private.sports_budget
                    where singleton=true and enabled=false and in_flight is null) then
    raise exception 'SITUATION_ROLLOUT_BUDGET_NOT_QUIESCENT' using errcode='22023';
  end if;
  if not exists(select 1 from pg_catalog.pg_class where oid='sefirot.chat_bridge_jobs'::regclass
       and relowner='postgres'::regrole and relkind='r' and relrowsecurity)
      or not exists(select 1 from pg_catalog.pg_namespace where nspname='sefirot'
                    and nspowner='postgres'::regrole)
      or exists(select 1 from pg_catalog.pg_namespace n cross join lateral
          pg_catalog.aclexplode(coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a
          where n.nspname='sefirot' and a.grantee<>'postgres'::regrole
            and (a.grantee is distinct from pg_catalog.to_regrole('sefirot_ingest')
              or a.privilege_type<>'USAGE' or a.is_grantable))
      -- Existing disabled ingestion identity is documented in supabase_ingest_role.sql.
      -- Preserve its narrow schema USAGE; do not create, grant or revoke it here.
      or exists(select 1 from pg_catalog.pg_roles r where r.rolname='sefirot_ingest'
          and (r.rolinherit or r.rolcanlogin or r.rolsuper or r.rolcreatedb
            or r.rolcreaterole or r.rolreplication or r.rolbypassrls
            or pg_catalog.has_table_privilege(r.oid,'sefirot.chat_bridge_jobs','SELECT,INSERT,UPDATE,DELETE')))
      or exists(select 1 from pg_catalog.pg_class c cross join lateral
          pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
          where c.oid='sefirot.chat_bridge_jobs'::regclass and a.grantee<>'postgres'::regrole)
      or exists(select 1 from pg_catalog.pg_attribute a cross join lateral
          pg_catalog.aclexplode(a.attacl) x
          where a.attrelid='sefirot.chat_bridge_jobs'::regclass and x.grantee<>'postgres'::regrole)
      or exists(select 1 from (values ('anon'),('authenticated'),('service_role')) r(name)
          where pg_catalog.has_schema_privilege(r.name,'sefirot','USAGE')
            or pg_catalog.has_table_privilege(r.name,'sefirot.chat_bridge_jobs','SELECT,INSERT,UPDATE,DELETE')) then
    raise exception 'SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT' using errcode='22023';
  end if;
  -- Do not rewrite any installed transport function. Reject an unknown baseline.
  for expected in select * from (values
    ('public.sefirot_chat_claim()',null::text,false,null::text[]),
    ('public.sefirot_chat_complete(uuid,boolean,jsonb,text)','9e377e91bf3cedd04f2a3f65924041fe0a8b7752f363d3d0d50167d278186fab',true,
       array['p_id','p_success','p_response','p_error']),
    ('public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','6e938616a18fec26c8e6ccefdb6f4abfa34f5c44deaf89a66dd40b02478c14c4',false,
       array['p_id','p_attempt','p_success','p_response','p_error']),
    ('sefirot.chat_complete_before_probe_fence(uuid,boolean,jsonb,text)',null::text,false,
       array['p_id','p_success','p_response','p_error'])
  ) v(signature,body_hash,service_execute,argnames) loop
    select p.*,l.lanname into f from pg_catalog.pg_proc p
      join pg_catalog.pg_language l on l.oid=p.prolang
      where p.oid=pg_catalog.to_regprocedure(expected.signature);
    if not found or f.proowner<>'postgres'::regrole or not f.prosecdef
        or f.proisstrict or f.proretset or f.pronargdefaults<>0
        or f.prorettype<>'jsonb'::regtype or f.lanname<>'plpgsql'
        or f.proconfig is distinct from array['search_path=""']
        or f.proargnames is distinct from expected.argnames
        or (expected.body_hash is not null and pg_catalog.encode(pg_catalog.sha256(
            pg_catalog.convert_to(f.prosrc,'UTF8')),'hex')<>expected.body_hash)
        or (expected.signature='public.sefirot_chat_claim()' and pg_catalog.encode(pg_catalog.sha256(
            pg_catalog.convert_to(f.prosrc,'UTF8')),'hex') not in ('97d93a6de4f246660565569edc2c46c214e1cfa615114a5852df075a98fcd25e','4bb9eee8436f42e018766c6927aacaa00def6f59a856664f7a9054e9cf45f267'))
        or (expected.signature like 'sefirot.%' and pg_catalog.encode(pg_catalog.sha256(
            pg_catalog.convert_to(f.prosrc,'UTF8')),'hex') not in ('ea4ffb3167bea44c83d5af1c088699debb92e0a4ab1570828e153f81bc4663f0','6d88b7f710d90b9f4cb7852fd57b1b02044b0f8fb52b6a75bc664801a43bc68b','02b68217bddbe0cb3bf54069f063c6e2ae6f2693cdf4b581e184ef0b30b29ad6','4df3982c504c8eafc7f1c95b615e02e3d907043325ca97939f9f95d9845b9d12'))
        or exists(select 1 from pg_catalog.aclexplode(coalesce(f.proacl,
            pg_catalog.acldefault('f',f.proowner))) a where a.grantee<>'postgres'::regrole
              and (not expected.service_execute or a.grantee<>'service_role'::regrole or a.is_grantable))
        or pg_catalog.has_function_privilege('service_role',f.oid,'EXECUTE')<>expected.service_execute
        or pg_catalog.has_function_privilege('anon',f.oid,'EXECUTE')
        or pg_catalog.has_function_privilege('authenticated',f.oid,'EXECUTE') then
      raise exception 'SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED' using errcode='22023';
    end if;
    if (select count(*) from pg_catalog.pg_proc p where p.pronamespace=f.pronamespace
        and p.proname=f.proname)<>1 then
      raise exception 'SITUATION_ROLLOUT_FENCE_OVERLOAD_DRIFT' using errcode='22023';
    end if;
  end loop;
  select pg_catalog.pg_get_constraintdef(oid) into actual_kind
    from pg_catalog.pg_constraint where conrelid='sefirot.chat_bridge_jobs'::regclass
      and conname='chat_bridge_jobs_kind_check' and contype='c'
      and convalidated and not condeferrable;
  if actual_kind is null or actual_kind not in ('CHECK ((kind = ANY (ARRAY[''status''::text, ''demo''::text, ''capture''::text, ''decide''::text, ''result''::text, ''report''::text, ''stake_snapshot''::text, ''sports_probe''::text])))','CHECK ((kind = ANY (ARRAY[''status''::text, ''demo''::text, ''capture''::text, ''decide''::text, ''result''::text, ''report''::text, ''stake_snapshot''::text, ''sports_probe''::text, ''situation''::text])))') then
    raise exception 'SITUATION_ROLLOUT_KIND_DRIFT' using errcode='22023';
  end if;
  select count(*) into object_count from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
    where (n.nspname='public' and p.proname in
      ('sefirot_situation_source','sefirot_situation_enqueue','sefirot_situation_complete'))
      or (n.nspname='sefirot' and p.proname='situation_receipt_append_only');
  if pg_catalog.to_regclass('sefirot.chat_situation_receipts') is null then
    if object_count<>0 or actual_kind<>'CHECK ((kind = ANY (ARRAY[''status''::text, ''demo''::text, ''capture''::text, ''decide''::text, ''result''::text, ''report''::text, ''stake_snapshot''::text, ''sports_probe''::text])))' then
      raise exception 'SITUATION_ROLLOUT_PARTIAL_BASELINE' using errcode='22023';
    end if;
  elsif object_count<>4 or actual_kind<>'CHECK ((kind = ANY (ARRAY[''status''::text, ''demo''::text, ''capture''::text, ''decide''::text, ''result''::text, ''report''::text, ''stake_snapshot''::text, ''sports_probe''::text, ''situation''::text])))' then
    raise exception 'SITUATION_ROLLOUT_PARTIAL_BASELINE' using errcode='22023';
  end if;
end $$;
do $install$ begin
  if pg_catalog.to_regclass('sefirot.chat_situation_receipts') is null then
    -- The following canonical definitions are copied byte-for-byte from the
    -- fresh-install schema. Existing instances are verified, never replaced.
    execute $canonical$
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
       or p_response->'source_identity' is distinct from item.request->'identity'
       or p_response->>'request_at' is distinct from item.request->>'request_at'
       or p_response->'monetary_permission' is distinct from 'false'::jsonb
       or p_response->'core_invoked' is distinct from 'false'::jsonb
       or p_response->'execution_enabled' is distinct from 'false'::jsonb
       or p_response->'prematch_core_allowed' is distinct from 'false'::jsonb
       or p_response->'live_betting_allowed' is distinct from 'false'::jsonb
       or p_response->'external_origin_verified' is distinct from 'false'::jsonb
       or p_error is not null))
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
$canonical$;
    alter table sefirot.chat_bridge_jobs drop constraint chat_bridge_jobs_kind_check;
    alter table sefirot.chat_bridge_jobs add constraint chat_bridge_jobs_kind_check
      check(kind in ('status','demo','capture','decide','result','report','stake_snapshot','sports_probe','situation'));
    revoke all on function public.sefirot_situation_source(text) from public,anon,authenticated,service_role;
    revoke all on function public.sefirot_situation_enqueue(jsonb) from public,anon,authenticated,service_role;
    revoke all on function public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) from public,anon,authenticated,service_role;
    grant execute on function public.sefirot_situation_source(text) to service_role;
  end if;
end $install$;
-- A default grant or unknown partial/drifted object fails this transaction.
-- No grants are silently repaired on a repeat application.
do $$
declare f record; expected record;
begin
  if not exists(select 1 from pg_catalog.pg_class c where c.oid='sefirot.chat_situation_receipts'::regclass
      and c.relkind='r' and c.relowner='postgres'::regrole and c.relpersistence='p'
      and c.relrowsecurity and not c.relforcerowsecurity and not c.relispartition)
      or (select count(*) from pg_catalog.pg_attribute where attrelid='sefirot.chat_situation_receipts'::regclass
          and attnum>0)<>3
      or exists(select 1 from pg_catalog.pg_attribute a left join pg_catalog.pg_attrdef d
            on d.adrelid=a.attrelid and d.adnum=a.attnum
          where a.attrelid='sefirot.chat_situation_receipts'::regclass and a.attnum>0
            and (a.attisdropped or not a.attnotnull or a.attidentity<>'' or a.attgenerated<>''
              or a.atttypmod<>-1 or a.attndims<>0
              or (a.attnum=1 and a.attcollation<>'default'::regcollation)
              or (a.attnum=1 and (a.attname<>'receipt_id' or a.atttypid<>'text'::regtype or d.oid is not null))
              or (a.attnum=2 and (a.attname<>'envelope' or a.atttypid<>'jsonb'::regtype or d.oid is not null))
              or (a.attnum=3 and (a.attname<>'registered_at' or a.atttypid<>'timestamptz'::regtype
                or pg_catalog.pg_get_expr(d.adbin,d.adrelid) is distinct from 'now()'))))
      or (select count(*) from pg_catalog.pg_constraint
          where conrelid='sefirot.chat_situation_receipts'::regclass and contype<>'n')<>3
      or exists(select 1 from (values
        ('chat_situation_receipts_pkey','PRIMARY KEY (receipt_id)'),
        ('chat_situation_receipts_receipt_id_check','CHECK ((receipt_id ~ ''^[0-9a-f]{64}$''::text))'),
        ('chat_situation_receipts_envelope_check','CHECK (((jsonb_typeof(envelope) = ''object''::text) AND (octet_length((envelope)::text) <= 65536)))')
      ) v(name,definition) where not exists(select 1 from pg_catalog.pg_constraint c
        where c.conrelid='sefirot.chat_situation_receipts'::regclass and c.conname=v.name
          and pg_catalog.pg_get_constraintdef(c.oid)=v.definition and c.convalidated
          and not c.condeferrable and not c.condeferred))
      or (select count(*) from pg_catalog.pg_index where indrelid='sefirot.chat_situation_receipts'::regclass)<>1
      or not exists(select 1 from pg_catalog.pg_index where indrelid='sefirot.chat_situation_receipts'::regclass
          and indisvalid and indisready and indisprimary and indisunique and indnkeyatts=1
          and indnatts=1 and indkey='1'::int2vector and indexprs is null and indpred is null)
      or exists(select 1 from pg_catalog.pg_policy where polrelid='sefirot.chat_situation_receipts'::regclass)
      or exists(select 1 from pg_catalog.pg_rewrite where ev_class='sefirot.chat_situation_receipts'::regclass)
      or exists(select 1 from pg_catalog.pg_inherits where inhrelid='sefirot.chat_situation_receipts'::regclass
                or inhparent='sefirot.chat_situation_receipts'::regclass) then
    raise exception 'SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT' using errcode='22023';
  end if;
  if exists(select 1 from pg_catalog.pg_class c cross join lateral
      pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
      where c.oid='sefirot.chat_situation_receipts'::regclass and a.grantee<>'postgres'::regrole)
      or exists(select 1 from pg_catalog.pg_attribute a cross join lateral pg_catalog.aclexplode(a.attacl) x
          where a.attrelid='sefirot.chat_situation_receipts'::regclass and x.grantee<>'postgres'::regrole)
      or exists(select 1 from (values ('anon'),('authenticated'),('service_role')) r(name)
          where pg_catalog.has_table_privilege(r.name,'sefirot.chat_situation_receipts','SELECT,INSERT,UPDATE,DELETE')) then
    raise exception 'SITUATION_ROLLOUT_RECEIPT_ACCESS_DRIFT' using errcode='22023';
  end if;
  if (select count(*) from pg_catalog.pg_trigger where tgrelid='sefirot.chat_situation_receipts'::regclass
      and not tgisinternal)<>1 or not exists(select 1 from pg_catalog.pg_trigger
      where tgrelid='sefirot.chat_situation_receipts'::regclass and tgname='situation_receipt_immutable'
        and tgfoid=pg_catalog.to_regprocedure('sefirot.situation_receipt_append_only()')
        and tgtype=27 and tgenabled='O' and tgnargs=0 and tgqual is null
        and tgconstraint=0 and tgattr=''::int2vector) then
    raise exception 'SITUATION_ROLLOUT_RECEIPT_TRIGGER_DRIFT' using errcode='22023';
  end if;
  for expected in select * from (values
    ('sefirot.situation_receipt_append_only()','32978629df1b6a82836be90defca416feb7c3147d005a3ae550b0cb72f458ba7',false,false,null::text[],'trigger'),
    ('public.sefirot_situation_source(text)','e9798a5c1931e96e60ef6f206936d0fc4d7f0dd74acd1aaf5ef0e5cca5053fd8',true,true,array['p_receipt_id']::text[],'jsonb'),
    ('public.sefirot_situation_enqueue(jsonb)','1f4649013058cab01e92514b6a8212d04fd72d44da4628b77d8b418eb214b7fc',true,false,array['p_request']::text[],'jsonb'),
    ('public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text)','d790cbb9548e3845a7dc21e43d9dd98b513d9248a9e6162af7defad3c85325e2',true,false,array['p_id','p_attempt','p_success','p_response','p_error']::text[],'jsonb')
  ) v(signature,body_hash,definer,service_execute,argnames,return_type) loop
    select p.*,l.lanname into f from pg_catalog.pg_proc p
      join pg_catalog.pg_language l on l.oid=p.prolang
      where p.oid=pg_catalog.to_regprocedure(expected.signature);
    if not found or f.proowner<>'postgres'::regrole or f.prosecdef<>expected.definer
        or f.proisstrict or f.proretset or f.pronargdefaults<>0 or f.proleakproof
        or f.provolatile<>'v' or f.proparallel<>'u' or f.lanname<>'plpgsql'
        or f.prorettype<>expected.return_type::regtype
        or f.proconfig is distinct from array['search_path=""']
        or f.proargnames is distinct from expected.argnames
        or pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(f.prosrc,'UTF8')),'hex')<>expected.body_hash
        or exists(select 1 from pg_catalog.aclexplode(coalesce(f.proacl,
            pg_catalog.acldefault('f',f.proowner))) a where a.grantee<>'postgres'::regrole
              and (not expected.service_execute or a.grantee<>'service_role'::regrole or a.is_grantable))
        or pg_catalog.has_function_privilege('service_role',f.oid,'EXECUTE')<>expected.service_execute
        or pg_catalog.has_function_privilege('anon',f.oid,'EXECUTE')
        or pg_catalog.has_function_privilege('authenticated',f.oid,'EXECUTE') then
      raise exception 'SITUATION_ROLLOUT_FUNCTION_DRIFT' using errcode='22023';
    end if;
  end loop;
end $$;
notify pgrst, 'reload schema';
commit;
