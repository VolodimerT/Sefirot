
create role anon;create role authenticated;create role service_role;
create schema sefirot;
revoke all on schema sefirot from public,anon,authenticated,service_role;
create table sefirot.chat_bridge_jobs (
 id uuid primary key,kind text not null,request jsonb not null,
 status text not null default 'PENDING',attempts integer not null default 0,
 submitted_at timestamptz not null default now(),claimed_at timestamptz,completed_at timestamptz,
 response jsonb,error text,
 constraint chat_bridge_jobs_kind_check check(kind in ('status','demo','capture','decide','result','report')),
 constraint chat_bridge_jobs_request_check check(jsonb_typeof(request)='object'),
 constraint chat_bridge_jobs_status_check check(status in ('PENDING','RUNNING','DONE','ERROR')),
 constraint chat_bridge_jobs_attempts_check check(attempts between 0 and 5)
);
alter table sefirot.chat_bridge_jobs enable row level security;
revoke all on sefirot.chat_bridge_jobs from public,anon,authenticated,service_role;
create function public.sefirot_chat_claim() returns jsonb
language plpgsql security definer set search_path='' as $$
declare item record;
begin
 select id,kind,request,attempts into item from sefirot.chat_bridge_jobs
 where (status='PENDING' or (status='RUNNING' and claimed_at<now()-interval '3 minutes'))
   and attempts<3 order by submitted_at,id for update skip locked limit 1;
 if not found then return pg_catalog.jsonb_build_object('job',null);end if;
 update sefirot.chat_bridge_jobs set status='RUNNING',attempts=attempts+1,claimed_at=now() where id=item.id;
 return pg_catalog.jsonb_build_object('job',pg_catalog.jsonb_build_object(
   'id',item.id,'kind',item.kind,'request',item.request,'attempt',item.attempts+1));
end $$;
revoke all on function public.sefirot_chat_claim() from public,anon,authenticated;
grant execute on function public.sefirot_chat_claim() to service_role;
create function public.sefirot_chat_complete(p_id uuid,p_success boolean,p_response jsonb,p_error text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item record;
begin
 select status,attempts into item from sefirot.chat_bridge_jobs where id=p_id for update;
 if not found or item.status<>'RUNNING' then raise exception 'INVALID_BRIDGE_JOB_STATE' using errcode='22023';end if;
 if (p_response is not null and pg_catalog.octet_length(p_response::text)>900000)
   or (p_error is not null and pg_catalog.length(p_error)>300) then raise exception 'INVALID_BRIDGE_JOB_RESULT_SIZE';end if;
 update sefirot.chat_bridge_jobs set status=case when p_success then 'DONE' else 'ERROR' end,
  completed_at=pg_catalog.now(),response=p_response,error=p_error where id=p_id;
 return pg_catalog.jsonb_build_object('completed',true,'id',p_id,'attempts',item.attempts);
end $$;
revoke all on function public.sefirot_chat_complete(uuid,boolean,jsonb,text) from public,anon,authenticated;
grant execute on function public.sefirot_chat_complete(uuid,boolean,jsonb,text) to service_role;
-- Isolated fixture for the existing CAS protocol, not a canonical table.
create table sefirot.test_bridge_snapshot(revision integer,snapshot text,checksum text);
insert into sefirot.test_bridge_snapshot values(0,null,null);
create function public.sefirot_bridge_pull() returns jsonb language sql security definer set search_path='' as $$
 select pg_catalog.jsonb_build_object('revision',revision,'snapshot',snapshot,'checksum',checksum)
 from sefirot.test_bridge_snapshot;
$$;
create function public.sefirot_bridge_save(p_revision integer,p_snapshot text,p_checksum text) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 update sefirot.test_bridge_snapshot set revision=revision+1,snapshot=p_snapshot,checksum=p_checksum
 where revision=p_revision;
 if not found then raise exception 'STALE_REVISION';end if;
 return pg_catalog.jsonb_build_object('revision',p_revision+1,'checksum',p_checksum);
end $$;
revoke all on function public.sefirot_bridge_pull() from public,anon,authenticated;
revoke all on function public.sefirot_bridge_save(integer,text,text) from public,anon,authenticated;
grant execute on function public.sefirot_bridge_pull() to service_role;
grant execute on function public.sefirot_bridge_save(integer,text,text) to service_role;
create table sefirot.predictions(id text primary key,payload jsonb);
insert into sefirot.predictions values('canonical-untouched','{"sealed":true}');
