-- Review-only until coordinated owner-approved deployment. No cron activation,
-- budget mutation, backfill, model writes, or changes to existing queue RPCs.
begin;
set local lock_timeout='3s';
set local statement_timeout='15s';
do $$ begin
  if current_user<>'postgres' or to_regclass('sefirot.chat_bridge_jobs') is null
      or to_regclass('sefirot_budget_private.sports_budget') is null
      or to_regclass('sefirot.sports_archive') is not null
      or to_regprocedure('public.sefirot_source_append(text,text,uuid,integer)') is not null then
    raise exception 'SOURCE_ARCHIVE_BASELINE_REQUIRED';
  end if;
end $$;
lock table sefirot.chat_bridge_jobs in share row exclusive mode;
lock table sefirot_budget_private.sports_budget in share mode;
do $$ begin
  if exists(select 1 from sefirot.chat_bridge_jobs where status in ('PENDING','RUNNING'))
      or not exists(select 1 from sefirot_budget_private.sports_budget where singleton and not enabled and in_flight is null) then
    raise exception 'SOURCE_ARCHIVE_QUIESCENT_BASELINE_REQUIRED';
  end if;
end $$;
create table sefirot.sports_archive(
 raw_sha256 text primary key check(raw_sha256 ~ '^[0-9a-f]{64}$'),
 raw_source text not null check(octet_length(raw_source) between 2 and 2000000),
 source_packet jsonb not null,
 imported_at timestamptz not null default clock_timestamp(),
 check(source_packet=raw_source::jsonb),
 check(raw_sha256=encode(sha256(convert_to(raw_source,'UTF8')),'hex'))
);
create table sefirot.sports_archive_links(
 raw_sha256 text not null references sefirot.sports_archive(raw_sha256),
 job_id uuid not null references sefirot.chat_bridge_jobs(id),
 attempt integer not null check(attempt between 1 and 3),
 linked_at timestamptz not null default clock_timestamp(),
 primary key(raw_sha256,job_id,attempt)
);
alter table sefirot.sports_archive enable row level security;
alter table sefirot.sports_archive_links enable row level security;
revoke all on sefirot.sports_archive,sefirot.sports_archive_links from public,anon,authenticated,service_role;
create function sefirot.source_archive_immutable() returns trigger language plpgsql set search_path='' as $$
begin raise exception 'SOURCE_ARCHIVE_IMMUTABLE';end $$;
revoke all on function sefirot.source_archive_immutable() from public,anon,authenticated,service_role;
create trigger source_archive_immutable before update or delete on sefirot.sports_archive
 for each row execute function sefirot.source_archive_immutable();
create trigger source_links_immutable before update or delete on sefirot.sports_archive_links
 for each row execute function sefirot.source_archive_immutable();

-- A durable intent is committed BEFORE provider I/O. Its unique query binding
-- prevents a repeated gateway call from fetching again after an uncertain reply.
create table sefirot.sports_source_dispatch(
 job_id uuid not null references sefirot.chat_bridge_jobs(id),
 query_hash text not null,attempt integer not null check(attempt between 1 and 3),
 started_at timestamptz not null default clock_timestamp(),primary key(job_id,query_hash)
);
alter table sefirot.sports_source_dispatch enable row level security;
revoke all on sefirot.sports_source_dispatch from public,anon,authenticated,service_role;
create trigger source_dispatch_immutable before update or delete on sefirot.sports_source_dispatch
 for each row execute function sefirot.source_archive_immutable();
create function public.sefirot_source_begin(p_job uuid,p_attempt integer,p_endpoint text,p_params jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare item record;q jsonb;today date:=(clock_timestamp() at time zone 'UTC')::date;
begin
 -- Lock serializes all dispatchers; the protected provider budget is unchanged.
 lock table sefirot.sports_source_dispatch in share row exclusive mode;
 select kind,status,attempts,request into item from sefirot.chat_bridge_jobs where id=p_job for share;
 q=jsonb_build_object('endpoint',p_endpoint,'params',p_params);
 if not found or item.kind<>'sports_probe' or item.status<>'RUNNING'
   or p_attempt is distinct from item.attempts or p_attempt<>1
   or not exists(select 1 from jsonb_array_elements(item.request->'queries') v where v=q)
 then raise exception 'SOURCE_DISPATCH_LEASE_REQUIRED';end if;
 if (select count(*) from sefirot.sports_source_dispatch where (started_at at time zone 'UTC')::date=today)>=5
   or (select count(*) from sefirot_budget_private.sports_attempt where (started_at at time zone 'UTC')::date=today)>=5
 then raise exception 'SOURCE_DISPATCH_DAILY_CAP';end if;
 insert into sefirot.sports_source_dispatch(job_id,query_hash,attempt)
 values(p_job,encode(sha256(convert_to(q::text,'UTF8')),'hex'),p_attempt) on conflict do nothing;
 if not found then raise exception 'SOURCE_DISPATCH_ALREADY_ATTEMPTED';end if;
 return jsonb_build_object('authorized',true);
end $$;

create function public.sefirot_source_append(p_raw text,p_hash text,p_job uuid,p_attempt integer)
returns jsonb language plpgsql security definer set search_path='' as $$
declare p jsonb;r jsonb;item record;ep text;seen jsonb;
begin
 if p_raw is null or octet_length(p_raw) not between 2 and 2000000
     or p_hash is null or p_hash<>encode(sha256(convert_to(p_raw,'UTF8')),'hex') then
   raise exception 'SOURCE_RAW_HASH_MISMATCH';
 end if;
 p=p_raw::jsonb;r=p->'receipt';ep=r->>'endpoint';
 if jsonb_typeof(p)<>'object' or (select count(*) from jsonb_object_keys(p))<>2
     or not p ?& array['data','receipt'] or jsonb_typeof(r)<>'object'
     or r->>'provider' is distinct from 'API_FOOTBALL_V3'
     or r->>'provider_host' is distinct from 'v3.football.api-sports.io'
     or r->>'transport' is distinct from 'SUPABASE_GATEWAY'
     or r->'sports_only' is distinct from 'true'::jsonb
     or r->'http_status' is distinct from '200'::jsonb
     or jsonb_typeof(r->'parameters') is distinct from 'object'
     or ep not in ('/fixtures','/fixtures/statistics','/fixtures/lineups','/status','/leagues','/teams/statistics')
     or ep is null or not (r->>'payload_hash' ~ '^[0-9a-f]{64}$')
     or r->>'payload_hash' is null
     or jsonb_typeof(p->'data') is distinct from 'object'
     or p->'data'->'errors' not in ('[]'::jsonb,'{}'::jsonb)
     or p->'data'->'errors' is null
     or not coalesce((r->>'request_started_at')::timestamptz <= (r->>'upstream_received_at')::timestamptz
        and (r->>'upstream_received_at')::timestamptz <= (r->>'received_at')::timestamptz
        and (r->>'received_at')::timestamptz <= clock_timestamp(),false)
     or jsonb_path_exists(p,'$.** ? (@.type() == "object").keyvalue() ? (@.key like_regex "^(authorization|headers|password|api[_-]?key)$|secret|token" flag "i")')
     or (ep='/status' and ((p->'data'->'response') - array['subscription','requests'])<>'{}'::jsonb) then
   raise exception 'SOURCE_PACKET_REJECTED';
 end if;
 -- JSONB drops duplicate keys. Reject ambiguity against the original JSON too.
 if exists(with recursive nodes(v) as (
   select p_raw::json union all
   select child.value from nodes n cross join lateral (
     select value from json_each(case when json_typeof(n.v)='object' then n.v else '{}'::json end)
     union all select value from json_array_elements(case when json_typeof(n.v)='array' then n.v else '[]'::json end)
   ) child
 ) select 1 from nodes where json_typeof(v)='object'
   and (select count(*)<>count(distinct key) from json_each(v))) then
   raise exception 'SOURCE_DUPLICATE_JSON_KEY';
 end if;
 -- Match Python's normalized key policy, including spaced/punctuated labels.
 if exists(with recursive nodes(v) as (
   select p_raw::json union all
   select child.value from nodes n cross join lateral (
     select value from json_each(case when json_typeof(n.v)='object' then n.v else '{}'::json end)
     union all select value from json_array_elements(case when json_typeof(n.v)='array' then n.v else '[]'::json end)
   ) child
 ) select 1 from nodes n cross join lateral json_object_keys(
     case when json_typeof(n.v)='object' then n.v else '{}'::json end) k
   where regexp_replace(lower(k),'[^a-z0-9]','','g') in ('apikey','authorization','password','headers')
     or regexp_replace(lower(k),'[^a-z0-9]','','g') like '%secret%'
     or regexp_replace(lower(k),'[^a-z0-9]','','g') like '%token%') then
   raise exception 'SOURCE_UNSAFE_JSON_KEY';
 end if;
 select kind,attempts,submitted_at,request into item from sefirot.chat_bridge_jobs where id=p_job for share;
 if not found or item.kind<>'sports_probe' or p_attempt is null or p_attempt not between 1 and 3
     or p_attempt>item.attempts or (r->>'request_started_at')::timestamptz<item.submitted_at
     or not exists(select 1 from jsonb_array_elements(item.request->'queries') q
       where '/'||(q->>'endpoint')=ep and q->'params'=r->'parameters') then
   raise exception 'SOURCE_JOB_BINDING_REQUIRED';
 end if;
 -- Late receipts may be archived even after lease expiry/terminal completion.
 -- They never finish/reopen a job and never authorize another provider call.
 insert into sefirot.sports_archive(raw_sha256,raw_source,source_packet)
   values(p_hash,p_raw,p) on conflict do nothing;
 select source_packet into seen from sefirot.sports_archive where raw_sha256=p_hash;
 if seen is distinct from p then raise exception 'SOURCE_HASH_CONFLICT';end if;
 insert into sefirot.sports_archive_links(raw_sha256,job_id,attempt)
   values(p_hash,p_job,p_attempt) on conflict do nothing;
 return jsonb_build_object('stored',true,'raw_sha256',p_hash);
end $$;

create function public.sefirot_source_status() returns jsonb
language sql security definer set search_path='' as $$
 select jsonb_build_object('schema','football-source-store-v1',
   'ready',has_function_privilege('service_role','public.sefirot_source_begin(uuid,integer,text,jsonb)','EXECUTE') and has_function_privilege('service_role','public.sefirot_source_append(text,text,uuid,integer)','EXECUTE'),
   'append_only',true,'monetary_permission',false);
$$;
create function public.sefirot_source_export(p_after text default '') returns jsonb
language sql security definer set search_path='' as $$
 select coalesce((select jsonb_build_object('raw_source',raw_source,'raw_sha256',raw_sha256,
   'imported_at',imported_at,'next',raw_sha256) from sefirot.sports_archive
   where raw_sha256>p_after order by raw_sha256 limit 1),jsonb_build_object('next',null));
$$;

-- Daily planning is owner-only and INERT until explicitly scheduled. It never
-- arms/refills the budget, and counts ALL queued sports queries/provider calls.
create function public.sefirot_plan_collection_day(p_league integer default 39,p_season integer default 2026)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare today date := (clock_timestamp() at time zone 'UTC')::date;
 used integer;added integer:=0;q jsonb;uid uuid;candidate record;
begin
 if current_user<>'postgres' or p_league is null or p_league<=0 or p_season is null or p_season not between 1990 and 2200 then
   raise exception 'SOURCE_PLANNER_OWNER_REQUIRED';
 end if;
 lock table sefirot.chat_bridge_jobs in share row exclusive mode;
 select greatest((select count(*) from sefirot_budget_private.sports_attempt where (started_at at time zone 'UTC')::date=today),
   (select coalesce(sum(jsonb_array_length(request->'queries')),0) from sefirot.chat_bridge_jobs
    where kind='sports_probe' and (submitted_at at time zone 'UTC')::date=today)) into used;
 if used>=5 then return jsonb_build_object('queued',0,'reason','DAILY_FIVE_ATTEMPT_CAP');end if;
 if not exists(select 1 from sefirot.sports_archive
   where source_packet->'receipt'->>'endpoint'='/fixtures'
    and source_packet->'receipt'->'parameters'=jsonb_build_object('league',p_league,'season',p_season)
    and ((source_packet->'receipt'->>'received_at')::timestamptz at time zone 'UTC')::date=today) then
   q=jsonb_build_object('endpoint','fixtures','params',jsonb_build_object('league',p_league,'season',p_season));
   -- An uncertain pending/error/full-calendar fetch is never silently retried.
   if not exists(select 1 from sefirot.chat_bridge_jobs j cross join lateral jsonb_array_elements(j.request->'queries') v
     where j.kind='sports_probe' and v=q and (j.status in ('PENDING','RUNNING','ERROR')
       or not exists(select 1 from sefirot.sports_archive a where a.source_packet->'receipt'->>'endpoint'='/'||(v->>'endpoint')
         and a.source_packet->'receipt'->'parameters'=v->'params' and (a.source_packet->'receipt'->>'request_started_at')::timestamptz>=j.submitted_at)
       or exists(select 1 from jsonb_array_elements(j.response->'queries') z where z->'endpoint'=v->'endpoint'
           and z->'params'=v->'params' and (z->>'status')='ERROR'))) then
     uid=md5(today::text||q::text)::uuid;
     insert into sefirot.chat_bridge_jobs(id,kind,request) values(uid,'sports_probe',jsonb_build_object('queries',jsonb_build_array(q))) on conflict do nothing;
     if found then added=added+1;end if;
   end if;
 end if;
 -- One full calendar query today, then up to four unseen confirmed-FT fixtures.
 for candidate in with fixtures as (
   select f, (a.source_packet->'receipt'->>'received_at')::timestamptz observed
   from sefirot.sports_archive a cross join lateral jsonb_array_elements(
    case when a.source_packet->'receipt'->>'endpoint'='/fixtures' and jsonb_typeof(a.source_packet->'data'->'response')='array'
      then a.source_packet->'data'->'response' else '[]'::jsonb end) f
   where f->'league'->'id'=to_jsonb(p_league) and f->'league'->'season'=to_jsonb(p_season)
 ), latest as (
   select distinct on(f->'fixture'->>'id') f,observed from fixtures order by f->'fixture'->>'id',observed desc
 ) select (f->'fixture'->>'id')::bigint fid from latest l
   where f->'fixture'->'status'->>'short'='FT'
    and jsonb_typeof(f->'score'->'fulltime'->'home')='number' and jsonb_typeof(f->'score'->'fulltime'->'away')='number'
    and (f->'fixture'->>'date')::timestamptz<observed
    and not exists(select 1 from fixtures old where old.f->'fixture'->>'id'=l.f->'fixture'->>'id'
       and (old.f->'teams' is distinct from l.f->'teams'
         or old.f->'fixture'->>'date' is distinct from l.f->'fixture'->>'date'
         or old.f->'fixture'->'status'->>'short'='FT' and old.f->'score'->'fulltime' is distinct from l.f->'score'->'fulltime'
         or old.observed=l.observed and old.f is distinct from l.f))
    and not exists(select 1 from sefirot.sports_archive a
     where a.source_packet->'receipt'->>'endpoint'='/fixtures/statistics'
      and a.source_packet->'receipt'->'parameters'->>'fixture'=f->'fixture'->>'id')
   order by (f->'fixture'->>'date')::timestamptz,(f->'fixture'->>'id')::bigint loop
   exit when used+added>=5;
   q=jsonb_build_object('endpoint','fixtures/statistics','params',jsonb_build_object('fixture',candidate.fid));
   if exists(select 1 from sefirot.chat_bridge_jobs j cross join lateral jsonb_array_elements(j.request->'queries') v
       where j.kind='sports_probe' and v=q) then continue;end if;
   uid=md5(today::text||q::text)::uuid;
   insert into sefirot.chat_bridge_jobs(id,kind,request) values(uid,'sports_probe',jsonb_build_object('queries',jsonb_build_array(q))) on conflict do nothing;
   if found then added=added+1;end if;
 end loop;
 return jsonb_build_object('queued',added,'daily_cap',5,'minute_limit',1,'reserve',5,'budget_changed',false);
end $$;

revoke all on function public.sefirot_source_begin(uuid,integer,text,jsonb),public.sefirot_source_append(text,text,uuid,integer),
 public.sefirot_source_status(),public.sefirot_source_export(text),
 public.sefirot_plan_collection_day(integer,integer) from public,anon,authenticated,service_role;
grant execute on function public.sefirot_source_status() to service_role;
-- Remain parked: source_append/export and daily planner require explicit rollout.
do $$ begin
 if exists(select 1 from pg_class c cross join lateral aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
   where c.oid in ('sefirot.sports_archive'::regclass,'sefirot.sports_archive_links'::regclass,'sefirot.sports_source_dispatch'::regclass)
     and a.grantee<>'postgres'::regrole)
 or exists(select 1 from pg_proc p cross join lateral aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
   where p.oid in ('public.sefirot_source_begin(uuid,integer,text,jsonb)'::regprocedure,'public.sefirot_source_append(text,text,uuid,integer)'::regprocedure,
     'public.sefirot_source_status()'::regprocedure,'public.sefirot_source_export(text)'::regprocedure,
     'public.sefirot_plan_collection_day(integer,integer)'::regprocedure,'sefirot.source_archive_immutable()'::regprocedure)
   and a.grantee<>'postgres'::regrole and not(p.proname='sefirot_source_status' and a.grantee='service_role'::regrole and not a.is_grantable)) then
   raise exception 'SOURCE_ARCHIVE_DEFAULT_GRANT_DRIFT';
 end if;
end $$;
notify pgrst,'reload schema';
commit;
