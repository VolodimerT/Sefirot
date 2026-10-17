/* Owned populated PostgreSQL upgrade proof. No external URLs or credentials. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {PGlite} from '@electric-sql/pglite';
const read=p=>readFile(new URL('../'+p,import.meta.url),'utf8');
const manifest=JSON.parse(await read('schema/situation_rollout_manifest.json'));
const up=await read(manifest.up);
const inside=sql=>sql.replace(/^begin;\s*$/mi,'').replace(/^commit;\s*$/mi,'');
const hash=s=>createHash('sha256').update(s).digest('hex');
export const rejectionCases = [
  {
    "name": "pending queue",
    "mutate": "insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values('00000000-0000-0000-0000-000000000088','status','{}','PENDING',1)",
    "error": "SITUATION_ROLLOUT_QUEUE_NOT_DRAINED",
    "stage": "both"
  },
  {
    "name": "running queue",
    "mutate": "insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values('00000000-0000-0000-0000-000000000088','status','{}','RUNNING',1)",
    "error": "SITUATION_ROLLOUT_QUEUE_NOT_DRAINED",
    "stage": "both"
  },
  {
    "name": "enabled budget",
    "mutate": "update sefirot_budget_private.sports_budget set enabled=true",
    "error": "SITUATION_ROLLOUT_BUDGET_NOT_QUIESCENT",
    "stage": "both"
  },
  {
    "name": "inflight budget",
    "mutate": "update sefirot_budget_private.sports_budget set in_flight='00000000-0000-0000-0000-000000000088'",
    "error": "SITUATION_ROLLOUT_BUDGET_NOT_QUIESCENT",
    "stage": "both"
  },
  {
    "name": "missing budget",
    "mutate": "delete from sefirot_budget_private.sports_budget",
    "error": "SITUATION_ROLLOUT_BUDGET_NOT_QUIESCENT",
    "stage": "both"
  },
  {
    "name": "queue RLS disabled",
    "mutate": "alter table sefirot.chat_bridge_jobs disable row level security",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "service schema access",
    "mutate": "grant usage on schema sefirot to service_role",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "unexpected schema grant",
    "mutate": "create role situation_unexpected;grant usage on schema sefirot to situation_unexpected",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "unexpected table grant",
    "mutate": "create role situation_unexpected;grant select on sefirot.chat_bridge_jobs to situation_unexpected",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "unexpected column grant",
    "mutate": "create role situation_unexpected;grant select(request) on sefirot.chat_bridge_jobs to situation_unexpected",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "claim body changed",
    "mutate": "create or replace function public.sefirot_chat_claim() returns jsonb language plpgsql security definer set search_path='' as $$begin return '{}'::jsonb;end$$",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "claim resumed",
    "mutate": "grant execute on function public.sefirot_chat_claim() to service_role",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "probe resumed",
    "mutate": "grant execute on function public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text) to service_role",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "claim public grant",
    "mutate": "grant execute on function public.sefirot_chat_claim() to public",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "inherited claim access",
    "mutate": "create role situation_unexpected;grant situation_unexpected to service_role;grant execute on function public.sefirot_chat_claim() to situation_unexpected",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "wrapper unknown grant",
    "mutate": "create role situation_unexpected;grant execute on function public.sefirot_chat_complete(uuid,boolean,jsonb,text) to situation_unexpected",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "wrapper body changed",
    "mutate": "create or replace function public.sefirot_chat_complete(p_id uuid,p_success boolean,p_response jsonb,p_error text) returns jsonb language plpgsql security definer set search_path='' as $$ begin return '{}'::jsonb;end $$",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "probe body changed",
    "mutate": "create or replace function public.sefirot_probe_complete(p_id uuid,p_attempt integer,p_success boolean,p_response jsonb,p_error text) returns jsonb language plpgsql security definer set search_path='' as $$ begin return '{}'::jsonb;end $$",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "delegate body changed",
    "mutate": "create or replace function sefirot.chat_complete_before_probe_fence(p_id uuid,p_success boolean,p_response jsonb,p_error text) returns jsonb language plpgsql security definer set search_path='' as $$ begin return '{}'::jsonb;end $$",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "claim overload",
    "mutate": "create function public.sefirot_chat_claim(integer) returns jsonb language sql as $$select null::jsonb$$",
    "error": "SITUATION_ROLLOUT_FENCE_OVERLOAD_DRIFT",
    "stage": "both"
  },
  {
    "name": "unknown kind",
    "mutate": "alter table sefirot.chat_bridge_jobs drop constraint chat_bridge_jobs_kind_check;alter table sefirot.chat_bridge_jobs add constraint chat_bridge_jobs_kind_check check(kind in ('status','sports_probe','stake_snapshot','unexpected'))",
    "error": "SITUATION_ROLLOUT_KIND_DRIFT",
    "stage": "both"
  },
  {
    "name": "partial table",
    "mutate": "create table sefirot.chat_situation_receipts(receipt_id text)",
    "error": "SITUATION_ROLLOUT_PARTIAL_BASELINE",
    "stage": "before"
  },
  {
    "name": "partial function",
    "mutate": "create function public.sefirot_situation_source(text) returns jsonb language sql as $$select null::jsonb$$",
    "error": "SITUATION_ROLLOUT_PARTIAL_BASELINE",
    "stage": "before"
  },
  {
    "name": "unexpected public function default",
    "mutate": "create role situation_unexpected;alter default privileges for role postgres in schema public grant execute on functions to situation_unexpected",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "before"
  },
  {
    "name": "unexpected private function default",
    "mutate": "create role situation_unexpected;alter default privileges for role postgres in schema sefirot grant execute on functions to situation_unexpected",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "before"
  },
  {
    "name": "unexpected table default",
    "mutate": "create role situation_unexpected;alter default privileges for role postgres in schema sefirot grant select on tables to situation_unexpected",
    "error": "SITUATION_ROLLOUT_RECEIPT_ACCESS_DRIFT",
    "stage": "before"
  },
  {
    "name": "receipt extra column",
    "mutate": "alter table sefirot.chat_situation_receipts add column unreviewed text",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt nullability",
    "mutate": "alter table sefirot.chat_situation_receipts alter column envelope drop not null",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt default",
    "mutate": "alter table sefirot.chat_situation_receipts alter column registered_at set default '2000-01-01'::timestamptz",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt RLS disabled",
    "mutate": "alter table sefirot.chat_situation_receipts disable row level security",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt check removed",
    "mutate": "alter table sefirot.chat_situation_receipts drop constraint chat_situation_receipts_envelope_check",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt policy added",
    "mutate": "create policy unreviewed on sefirot.chat_situation_receipts using (true)",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt extra index",
    "mutate": "create index unreviewed on sefirot.chat_situation_receipts(registered_at)",
    "error": "SITUATION_ROLLOUT_RECEIPT_SCHEMA_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt unknown grant",
    "mutate": "create role situation_unexpected;grant select on sefirot.chat_situation_receipts to situation_unexpected",
    "error": "SITUATION_ROLLOUT_RECEIPT_ACCESS_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt column grant",
    "mutate": "create role situation_unexpected;grant select(envelope) on sefirot.chat_situation_receipts to situation_unexpected",
    "error": "SITUATION_ROLLOUT_RECEIPT_ACCESS_DRIFT",
    "stage": "after"
  },
  {
    "name": "disabled append-only trigger",
    "mutate": "alter table sefirot.chat_situation_receipts disable trigger situation_receipt_immutable",
    "error": "SITUATION_ROLLOUT_RECEIPT_TRIGGER_DRIFT",
    "stage": "after"
  },
  {
    "name": "receipt extra trigger",
    "mutate": "create trigger unreviewed before update on sefirot.chat_situation_receipts for each row execute function sefirot.situation_receipt_append_only()",
    "error": "SITUATION_ROLLOUT_RECEIPT_TRIGGER_DRIFT",
    "stage": "after"
  },
  {
    "name": "trigger body changed",
    "mutate": "create or replace function sefirot.situation_receipt_append_only() returns trigger language plpgsql security invoker set search_path='' as $$begin return new;end$$",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "source grant removed",
    "mutate": "revoke execute on function public.sefirot_situation_source(text) from service_role",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "enqueue resumed",
    "mutate": "grant execute on function public.sefirot_situation_enqueue(jsonb) to service_role",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "inherited completion access",
    "mutate": "create role situation_unexpected;grant situation_unexpected to service_role;grant execute on function public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) to situation_unexpected",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "unknown trigger grant",
    "mutate": "create role situation_unexpected;grant execute on function sefirot.situation_receipt_append_only() to situation_unexpected",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "complete unsafe search path",
    "mutate": "alter function public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) set search_path='public'",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "complete overload",
    "mutate": "create function public.sefirot_situation_complete(integer) returns jsonb language sql as $$select null::jsonb$$",
    "error": "SITUATION_ROLLOUT_PARTIAL_BASELINE",
    "stage": "after"
  },
  {
    "name": "ingest CREATE",
    "mutate": "grant create on schema sefirot to sefirot_ingest",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest USAGE grant option",
    "mutate": "grant usage on schema sefirot to sefirot_ingest with grant option",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest queue access",
    "mutate": "grant select on sefirot.chat_bridge_jobs to sefirot_ingest",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role LOGIN",
    "mutate": "alter role sefirot_ingest LOGIN",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role INHERIT",
    "mutate": "alter role sefirot_ingest INHERIT",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role SUPERUSER",
    "mutate": "alter role sefirot_ingest SUPERUSER",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role CREATEDB",
    "mutate": "alter role sefirot_ingest CREATEDB",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role CREATEROLE",
    "mutate": "alter role sefirot_ingest CREATEROLE",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role REPLICATION",
    "mutate": "alter role sefirot_ingest REPLICATION",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "ingest role BYPASSRLS",
    "mutate": "alter role sefirot_ingest BYPASSRLS",
    "error": "SITUATION_ROLLOUT_PRIVATE_ACCESS_DRIFT",
    "stage": "both"
  },
  {
    "name": "wrapper service grant option",
    "mutate": "grant execute on function public.sefirot_chat_complete(uuid,boolean,jsonb,text) to service_role with grant option",
    "error": "SITUATION_ROLLOUT_PARKED_FENCE_REQUIRED",
    "stage": "both"
  },
  {
    "name": "source service grant option",
    "mutate": "grant execute on function public.sefirot_situation_source(text) to service_role with grant option",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  },
  {
    "name": "ingest new receipt access",
    "mutate": "grant select on sefirot.chat_situation_receipts to sefirot_ingest",
    "error": "SITUATION_ROLLOUT_RECEIPT_ACCESS_DRIFT",
    "stage": "after"
  },
  {
    "name": "ingest new source access",
    "mutate": "grant execute on function public.sefirot_situation_source(text) to sefirot_ingest",
    "error": "SITUATION_ROLLOUT_FUNCTION_DRIFT",
    "stage": "after"
  }
];
// END_REJECTION_CASES
const request = {"fixture_id": "synthetic:fixture:123", "provider_status": "NS", "kickoff": "2030-01-01T14:00:00+00:00", "status_observed_at": "2030-01-01T11:59:58+00:00", "request_at": "2030-01-01T12:00:00+00:00", "intent": "auto", "depth": "auto", "original_provider_receipt_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "identity": {"source_id": "synthetic-source", "source_revision": 1, "receipt_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "model_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}};
const response = {"schema": "sefirot-situation-status-v1", "fixture_id": "synthetic:fixture:123", "original_provider_receipt_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "source_identity": {"source_id": "synthetic-source", "source_revision": 1, "receipt_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "model_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}, "request_at": "2030-01-01T12:00:00+00:00", "monetary_permission": false, "core_invoked": false, "execution_enabled": false, "prematch_core_allowed": false, "live_betting_allowed": false, "external_origin_verified": false};
const documentedIngestSQL = `create role sefirot_ingest nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls;
grant usage on schema sefirot to sefirot_ingest;`;
const originalStateSQL = `select jsonb_build_object(
 'schema_acl',(select nspacl::text from pg_namespace where nspname='sefirot'),
 'ingest_flags',(select jsonb_build_object('name',rolname,'inherit',rolinherit,'login',rolcanlogin,
   'superuser',rolsuper,'createdb',rolcreatedb,'createrole',rolcreaterole,'replication',rolreplication,
   'bypassrls',rolbypassrls) from pg_roles where rolname='sefirot_ingest'),
 'jobs',(select coalesce(jsonb_agg(to_jsonb(j) order by id),'[]') from sefirot.chat_bridge_jobs j),
 'predictions',(select jsonb_agg(to_jsonb(p) order by id) from sefirot.predictions p),
 'snapshot',(select jsonb_agg(to_jsonb(s)) from sefirot.test_bridge_snapshot s),
 'budget',(select jsonb_agg(to_jsonb(b)) from sefirot_budget_private.sports_budget b),
 'fences',(select jsonb_agg(jsonb_build_object('name',p.proname,'definition',pg_get_functiondef(p.oid),'acl',p.proacl::text) order by p.proname)
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('sefirot','public')
   and p.proname in ('sefirot_chat_claim','sefirot_chat_complete','sefirot_probe_complete','chat_complete_before_probe_fence')),
 'other_constraints',(select jsonb_agg(jsonb_build_object('name',conname,'definition',pg_get_constraintdef(oid)) order by conname)
  from pg_constraint where conrelid='sefirot.chat_bridge_jobs'::regclass and conname<>'chat_bridge_jobs_kind_check')
) value`;
const baselineStateSQL = `select jsonb_build_object(
 'functions',(select jsonb_agg(jsonb_build_object('name',p.proname,'definition',pg_get_functiondef(p.oid),'acl',p.proacl::text) order by p.proname)
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('sefirot','public')
   and p.proname in ('situation_receipt_append_only','sefirot_situation_source','sefirot_situation_enqueue','sefirot_situation_complete')),
 'receipt_table',(select jsonb_agg(to_jsonb(r) order by receipt_id) from sefirot.chat_situation_receipts r),
 'receipt_columns',(select jsonb_agg(jsonb_build_object('name',attname,'type',atttypid,'notnull',attnotnull,'acl',attacl::text) order by attnum)
   from pg_attribute where attrelid='sefirot.chat_situation_receipts'::regclass and attnum>0),
 'kind',(select pg_get_constraintdef(oid) from pg_constraint where conrelid='sefirot.chat_bridge_jobs'::regclass and conname='chat_bridge_jobs_kind_check')
) value`;
const catalogStateSQL = `select jsonb_build_object(
 'tables',(select jsonb_agg(to_jsonb(c) order by c.oid) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='sefirot'),
 'columns',(select jsonb_agg(to_jsonb(a) order by a.attrelid,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='sefirot'),
 'constraints',(select jsonb_agg(to_jsonb(c) order by c.oid) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='sefirot'),
 'functions',(select jsonb_agg(to_jsonb(p) order by p.oid) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','sefirot') and p.proname like '%situation%'),
 'triggers',(select jsonb_agg(to_jsonb(t) order by t.oid) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='sefirot')
) value`;
const populatedWitnessSQL = `insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts,response,completed_at)
 values('00000000-0000-0000-0000-000000000089','stake_snapshot','{"original":true}','DONE',1,
 '{"sealed":"SYNTHETIC_ORIGINAL_BYTES"}','2026-10-15T10:00:00Z');
update sefirot.test_bridge_snapshot set revision=59,snapshot='SYNTHETIC_ORIGINAL_GZIP_BYTES',checksum=repeat('d',64);`;
const parkedAssertionsSQL = `do $$begin
 if has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE')
  or has_function_privilege('service_role','public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','EXECUTE')
  or has_function_privilege('service_role','public.sefirot_situation_enqueue(jsonb)','EXECUTE')
  or has_function_privilege('service_role','public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text)','EXECUTE')
  or not has_function_privilege('service_role','public.sefirot_situation_source(text)','EXECUTE') then raise exception 'NOT_PARKED';end if;
 if not exists(select 1 from pg_constraint where conrelid='sefirot.chat_bridge_jobs'::regclass
   and conname='chat_bridge_jobs_kind_check' and pg_get_constraintdef(oid) like '%stake_snapshot%'
   and pg_get_constraintdef(oid) like '%situation%') then raise exception 'KIND_LOST';end if;
end$$;`;

const state=async(pg,sql)=>(await pg.query(sql)).rows[0].value;
async function rejectsUnchanged(pg,c,after) {
 await pg.exec('savepoint fault');
 try {
  await pg.exec(c.mutate);
  const original=await state(pg,originalStateSQL),catalog=await state(pg,catalogStateSQL);
  await pg.exec('savepoint application');
  await assert.rejects(pg.exec(inside(up)),new RegExp(c.error),c.name);
  await pg.exec('rollback to savepoint application;release savepoint application');
  assert.deepEqual(await state(pg,originalStateSQL),original,c.name);
  assert.deepEqual(await state(pg,catalogStateSQL),catalog,c.name);
 } finally {await pg.exec('rollback to savepoint fault;release savepoint fault');}
}
async function denied(pg,sql,error) {
 await pg.exec('savepoint denial');
 await pg.exec('set role service_role');
 await assert.rejects(pg.exec(sql),error);
 await pg.exec('rollback to savepoint denial;release savepoint denial');
}
export async function situationUpgradeTests() {
 const pg=new PGlite();let groups=0;
 try {
  await pg.exec('begin');
  for(const f of ['tests/fixtures/chat_bridge_legacy.sql','tests/fixtures/probe_rollout_legacy.sql',
      manifest.required_probe_up,manifest.required_probe_park]) await pg.exec(inside(await read(f)));
  await pg.exec(populatedWitnessSQL);
  // The documented ingestion role is optional; prove the no-role upgrade too.
  await pg.exec('savepoint without_ingest');await pg.exec(inside(up));
  await pg.exec('rollback to savepoint without_ingest;release savepoint without_ingest');groups++;
  await pg.exec(documentedIngestSQL);
  const original=await state(pg,originalStateSQL);
  // Reproduce the deployed-blocking old path before applying the safe delta.
  await pg.exec('savepoint unsafe_previous_path');
  await assert.rejects(pg.exec(inside(await read('schema/supabase_chat_situation.sql'))),/chat_bridge_jobs_kind_check/);
  await pg.exec('rollback to savepoint unsafe_previous_path;release savepoint unsafe_previous_path');
  assert.deepEqual(await state(pg,originalStateSQL),original);groups++;
  assert.equal((await pg.query("select to_regclass('sefirot.chat_situation_receipts') absent")).rows[0].absent,null);
  for(const c of rejectionCases.filter(c=>c.stage!=='after')) {await rejectsUnchanged(pg,c,false);groups++;}
  await pg.exec('savepoint interrupted');
  await assert.rejects(pg.exec(inside(up)+"\ndo $$begin raise exception 'SYNTHETIC_INTERRUPTION';end$$;"),/SYNTHETIC_INTERRUPTION/);
  await pg.exec('rollback to savepoint interrupted;release savepoint interrupted');
  assert.deepEqual(await state(pg,originalStateSQL),original);
  assert.equal((await pg.query("select to_regclass('sefirot.chat_situation_receipts') absent")).rows[0].absent,null);groups++;
  await pg.exec(inside(up));
  assert.deepEqual(await state(pg,originalStateSQL),original);await pg.exec(parkedAssertionsSQL);groups++;
  const baseline=await state(pg,baselineStateSQL);
  await pg.exec(inside(up));assert.deepEqual(await state(pg,originalStateSQL),original);
  assert.deepEqual(await state(pg,baselineStateSQL),baseline);groups++;
  for(const c of rejectionCases.filter(c=>c.stage!=='before')) {await rejectsUnchanged(pg,c,true);groups++;}
  for(const f of manifest.functions) {
   const row=(await pg.query("select prosrc from pg_proc where oid=to_regprocedure($1)",[f.signature])).rows[0];
   assert.equal(hash(row.prosrc),f.body_sha256);
  }groups++;
  const envelope={body:{origin:'SYNTHETIC_TEST_ONLY',original_json:'{"provider":"owned"}'},collector_signature:'synthetic'};
  await pg.query('insert into sefirot.chat_situation_receipts(receipt_id,envelope) values($1,$2)',['a'.repeat(64),envelope]);
  await pg.exec('set role service_role');
  assert.deepEqual((await pg.query('select public.sefirot_situation_source($1) value',['a'.repeat(64)])).rows[0].value,{receipt:envelope});
  await pg.exec('reset role');groups++;
  for(const sql of ["select public.sefirot_chat_claim()", "select public.sefirot_probe_complete(null,1,false,null,'RESEARCH_RUNNER_ERROR')",
   'select public.sefirot_situation_enqueue(null)', 'select public.sefirot_situation_complete(null,1,false,null,null)',
   'select * from sefirot.chat_situation_receipts']) {await denied(pg,sql,/permission denied/);groups++;}
  for(const sql of ["update sefirot.chat_situation_receipts set envelope='{}'","delete from sefirot.chat_situation_receipts"]) {
   await pg.exec('savepoint immutable');await assert.rejects(pg.exec(sql),/APPEND_ONLY/);
   await pg.exec('rollback to savepoint immutable;release savepoint immutable');groups++;
  }
  // Synthetic LOCAL grants exercise compatible RPCs. This is NOT rollout SQL.
  await pg.exec('grant execute on function public.sefirot_chat_claim(),public.sefirot_situation_enqueue(jsonb),public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) to service_role');
  await pg.exec('set role service_role');
  const first=(await pg.query('select public.sefirot_situation_enqueue($1) value',[request])).rows[0].value;
  assert.equal((await pg.query('select public.sefirot_situation_enqueue($1) value',[request])).rows[0].value.reused,true);
  let job=(await pg.query('select public.sefirot_chat_claim() value')).rows[0].value.job;
  assert.equal(job.id,first.job_id);assert.equal(job.attempt,1);
  await pg.exec('reset role');
  await denied(pg,`select public.sefirot_situation_complete('${job.id}',2,true,'${JSON.stringify(response)}',null)`,/STALE_SITUATION_LEASE/);
  await denied(pg,`select public.sefirot_chat_complete('${job.id}',true,'{}',null)`,/SITUATION_LEASE_REQUIRED/);
  await pg.query("update sefirot.chat_bridge_jobs set claimed_at=now()-interval '4 minutes' where id=$1",[job.id]);
  await pg.exec('set role service_role');
  job=(await pg.query('select public.sefirot_chat_claim() value')).rows[0].value.job;assert.equal(job.attempt,2);
  const args=[job.id,2,true,response,null];
  assert.equal((await pg.query('select public.sefirot_situation_complete($1,$2,$3,$4,$5) value',args)).rows[0].value.completed,true);
  assert.equal((await pg.query('select public.sefirot_situation_complete($1,$2,$3,$4,$5) value',args)).rows[0].value.completed,true);
  await pg.exec('reset role');groups++;
  await denied(pg,`select public.sefirot_situation_complete('${job.id}',2,true,'${JSON.stringify({...response,execution_enabled:true})}',null)`,/INVALID_SITUATION_RESPONSE/);groups++;
  await pg.exec('revoke execute on function public.sefirot_chat_claim(),public.sefirot_situation_enqueue(jsonb),public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text) from service_role');
  const finalOriginal=await state(pg,originalStateSQL),finalBaseline=await state(pg,baselineStateSQL);
  await pg.exec(inside(up));assert.deepEqual(await state(pg,originalStateSQL),finalOriginal);
  assert.deepEqual(await state(pg,baselineStateSQL),finalBaseline);await pg.exec(parkedAssertionsSQL);groups++;
  await pg.exec('rollback');
 } finally {await pg.close();}
 return groups;
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===resolve(process.argv[1])) {
 console.log(JSON.stringify({situation_upgrade_groups:await situationUpgradeTests(),provider_calls:0,synthetic_only:true}));
}
