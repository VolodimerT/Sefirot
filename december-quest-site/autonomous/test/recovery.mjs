// Run the installed cron command against PGlite. Only the pg_cron catalog,
// timer ticks and pg_net queue delivery are emulated. All predictor SQL is real.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
import {execute} from '../run.js';
import {fixture,form,weekly,columns,freeze,tablePrefix} from './acceptance.mjs';
import {flightRpc} from './flight-rpc.mjs';

const sql=name=>readFile(new URL(name,import.meta.url),'utf8');
const db=new PGlite();
const rows=async(query,args)=>(await db.query(query,args)).rows;
let now, fault;
const clock=()=>now;
const stats={csv:0,commit:0};
const original="insert into qa_queue(url) values ('https://example.invalid/functions/v1/dq-autonomous-predictor-v63')";
async function tick(minute){
  const stamp='2026-12-01T17:'+String(minute).padStart(2,'0')+':00Z';
  now=Date.parse(stamp);
  await db.query("select set_config('qa.clock',$1,false)",[stamp]);
  const [job]=await rows('select command from cron.job');
  await db.exec(job.command);
}
async function rest(path,options){
  const p=JSON.parse(options?.body||'{}');
  if(path.includes('_fixtures?')){
    if(fault==='REST')throw Error('simulated REST timeout');
    return [{...fixture,checked_at:'2026-12-01T16:55:00Z'}];
  }
  if(path==='rpc/dq_finish_scheduled_predictor'){
    stats.commit++;
    if(fault==='DELAYED_COMMIT')await db.query("select set_config('qa.clock',$1,false)",[p.p_until]);
    if(fault==='SQL')p.p_forecasts={invalid:true};
  }
  const result=await flightRpc(rows,path,p);
  if(fault==='LOST_ACK'&&path==='rpc/dq_finish_scheduled_predictor')throw Error('lost commit reply');
  return result;
}
async function deliver(){
  const messages=await rows('delete from qa_queue returning url');
  assert.equal(messages.length,1);
  const params=new URL(messages[0].url).searchParams;
  const retry=params.get('retry_until')??params.get('run_until');
  assert.match(retry,/^\d{13}$/);
  return execute({clock,rest,retryUntil:retry===null?null:Number(retry),csv:async url=>{
    stats.csv++;
    if(fault==='PARTIAL'&&url.includes('/2526/'))throw Error('archive unavailable');
    return url.endsWith('/fixtures.csv')?weekly:[columns,...form.map(r=>url.includes('/2526/')?r.replace('/2026,','/2025,'):r)].join('\n');
  }});
}
async function reset(){
  await db.exec('truncate qa_queue, dq_predictor_dispatch_slots, dq_predictor_leases; delete from '+tablePrefix+'auto_runs');
}
try{
  await db.exec("create function dq_test_clock() returns timestamptz language sql stable as $$ select current_setting('qa.clock')::timestamptz $$");
  await db.exec(freeze(await sql('schema.sql')));
  await db.exec(freeze(await sql('../persist.sql')));
  await db.exec(freeze(await sql('../single-flight.sql')));
  await db.exec(freeze(await sql('../recovery-finish.sql')));
  await db.exec(`create schema cron;
    create table cron.job(jobid bigint,jobname text,username text,schedule text,command text,active boolean);
    create function cron.alter_job(bigint,schedule text,command text) returns void language sql as
    $$update cron.job set schedule=$2,command=$3 where jobid=$1$$;
    create table qa_queue(url text);`);
  await db.query("insert into cron.job values(71,'dq-autonomous-dec2026-19kyiv',current_user,'0 17 * * *',$1,true)",[original]);
  await db.exec(freeze(await sql('../recovery.sql')));
  await db.query('insert into '+tablePrefix+"fixtures(fixture_key,kickoff,competition,home_team,away_team,source_name,source_url) values($1,$2,'EPL',$3,$4,'qa','https://example.invalid')",
    [fixture.fixture_key,fixture.kickoff,fixture.home_team,fixture.away_team]);
  // Owner dies after claiming. The existing job re-dispatches after TTL.
  await tick(0);await db.exec('delete from qa_queue');
  const [old]=await rows("select dq_claim_predictor_run('DQ-POISSON-0.3') as claim");
  await tick(12);await tick(12);assert.equal((await deliver()).sealed,1);
  await assert.rejects(rows("select dq_finish_predictor_run($1,'{}','[]','[]','[]')",[old.claim.token]),/LEASE_LOST/);
  await tick(24);assert.equal((await rows('select * from qa_queue')).length,0);
  for(const problem of ['REST','SQL','DELAYED_COMMIT','LOST_ACK','PARTIAL']){
    await reset();await tick(0);fault=problem;
    if(problem==='PARTIAL')assert.equal((await deliver()).status,'PARTIAL');
    else if(problem==='DELAYED_COMMIT')await assert.rejects(deliver(),/RECOVERY_WINDOW_CLOSED/);
    else await assert.rejects(deliver());
    fault=null;
    await tick(12);
    if(problem!=='LOST_ACK')assert.equal((await deliver()).status,'OK');
    else assert.equal((await rows('select * from qa_queue')).length,0);
    await tick(24);assert.equal((await rows('select * from qa_queue')).length,0);
  }
  // Total outage consumes the three slots once. Delayed queue delivery expires.
  await reset();fault='REST';
  for(const slot of [0,12,24]){await tick(slot);await assert.rejects(deliver());await tick(slot);}
  for(const minute of [25,36,48])await tick(minute);
  assert.equal((await rows('select * from qa_queue')).length,0);
  assert.equal((await rows('select * from dq_predictor_dispatch_slots')).length,3);
  await reset();await tick(24);now=Date.parse(fixture.kickoff)+1;
  await db.query("select set_config('qa.clock',$1,false)",[new Date(now).toISOString()]);
  const before=stats.csv;await assert.rejects(deliver(),/RECOVERY_WINDOW_CLOSED/);assert.equal(stats.csv,before);
  const beforeRows=await rows('select * from '+tablePrefix+'auto_snapshots');
  assert.equal(beforeRows.length,1);
  await db.exec(await sql('../recovery-rollback.sql'));
  assert.deepEqual(await rows('select jobid,schedule,command from cron.job'),[{jobid:71,schedule:'0 17 * * *',command:original}]);
  assert.deepEqual(await rows('select * from '+tablePrefix+'auto_snapshots'),beforeRows);

  // Migration fixture matches the client insert contract. Old receipts remain readable.
  await db.exec("create table sefirot_december_quest_seals(kind text,payload jsonb); insert into sefirot_december_quest_seals values('tour','{}')");
  await db.exec(await sql('../manual-tour-policy.sql'));
  const insert=payload=>db.query("insert into sefirot_december_quest_seals values('tour',$1)",[payload]);
  const pass={kind:'tour',snapshot:{mode:'pass',verdict:'пропуск',riskClass:'D',decisionNote:'Missing evidence',legs:[]}};
  await insert(pass);
  for(const bad of [{},null,{...pass,snapshot:{...pass.snapshot,verdict:'играбельно'}},
    {...pass,snapshot:{...pass.snapshot,legs:[{enabled:true}]}}, {...pass,snapshot:{...pass.snapshot,mode:'original'}}])
    await assert.rejects(insert(bad),/dq_v212_tour_policy/);
  await db.exec('alter table sefirot_december_quest_seals drop constraint dq_v212_tour_policy');
  assert.equal((await rows('select * from sefirot_december_quest_seals')).length,2);
  console.log('PASS scheduled recovery, bounded dispatch, lost owner/ack, SQL/REST/source failures, late delivery, policy and rollback');
}finally{await db.close();}
