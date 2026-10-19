import assert from 'node:assert/strict';
import fs from 'node:fs';
import {PGlite} from '@electric-sql/pglite';
const sql=path=>fs.readFileSync(new URL('../'+path,import.meta.url),'utf8');
const inside=text=>text.replace(/^begin;\s*$/m,'').replace(/^commit;\s*$/m,'');
const up=inside(sql('supabase/migrations/20261015161027_probe_completion_fence.sql'));
const park=inside(sql('supabase/review_only/20261015161311_park_probe_queue.sql'));
const resume=inside(sql('supabase/migrations/20261017114454_resume_probe_worker.sql'));
const pg=new PGlite();let groups=0;
try {
 await pg.exec(sql('tests/fixtures/chat_bridge_legacy.sql'));
 await pg.exec(sql('tests/fixtures/probe_rollout_legacy.sql'));
 await pg.exec(up);await pg.exec(park);
 const state=async()=>({rows:(await pg.query('select * from sefirot.chat_bridge_jobs order by id')).rows,
   budget:(await pg.query('select * from sefirot_budget_private.sports_budget')).rows});
 const before=await state();
 await pg.exec(resume);await pg.exec(resume);assert.deepEqual(await state(),before);groups++;
 assert.equal((await pg.query("select has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE') as allowed")).rows[0].allowed,true);groups++;
 assert.equal((await pg.query("select has_function_privilege('service_role','public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','EXECUTE') as allowed")).rows[0].allowed,true);groups++;
 for (const fault of [
  ["insert into sefirot.chat_bridge_jobs(id,kind,request) values('00000000-0000-0000-0000-000000000091','capture','{}')",'QUEUE_REVIEW_REQUIRED'],
  ["insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values('00000000-0000-0000-0000-000000000091','sports_probe','{}','RUNNING',1)",'QUEUE_REVIEW_REQUIRED'],
  ["update sefirot_budget_private.sports_budget set in_flight='00000000-0000-0000-0000-000000000091'",'IN_FLIGHT_BUDGET'],
  ['grant execute on function public.sefirot_chat_claim() to anon','FUNCTION_ACCESS_DRIFT'],
  ['grant usage on schema sefirot to service_role','PRIVATE_ACCESS_DRIFT'],
  ["create or replace function public.sefirot_chat_claim() returns jsonb language sql security definer set search_path='' as $$select '{}'::jsonb$$",'FUNCTION_DRIFT'],
 ]) {
  await pg.exec('begin');await pg.exec(fault[0]);await pg.exec('savepoint apply');
  await assert.rejects(pg.exec(resume),new RegExp(fault[1]));
  await pg.exec('rollback');assert.deepEqual(await state(),before);groups++;
 }
 // Real PostgreSQL role -> claim -> leased completion -> identical replay.
 await pg.exec("insert into sefirot.chat_bridge_jobs(id,kind,request) values('00000000-0000-0000-0000-000000000092','sports_probe','{\"queries\":[{\"endpoint\":\"status\",\"params\":{}}]}')");
 await pg.exec('set role service_role');
 const claimed=(await pg.query('select public.sefirot_chat_claim() as value')).rows[0].value;
 assert.equal(claimed.job.attempt,1);assert.equal(claimed.job.kind,'sports_probe');
 const complete="select public.sefirot_probe_complete('00000000-0000-0000-0000-000000000092',1,false,null,'RESEARCH_RUNNER_ERROR') as value";
 assert.deepEqual((await pg.query(complete)).rows,(await pg.query(complete)).rows);
 assert.equal((await pg.query('select public.sefirot_chat_claim() as value')).rows[0].value.job,null);
 await pg.exec('reset role');await pg.exec(park);groups++;
 console.log(JSON.stringify({groups,source:'SYNTHETIC_ONLY'}));
} finally {await pg.close();}
