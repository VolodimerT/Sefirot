// Disposable local PostgreSQL only. No external DB URL or provider credentials accepted.
import assert from 'node:assert/strict';
import {fork} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {createHash,randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {setTimeout as delay} from 'node:timers/promises';

const require=createRequire(import.meta.url);
const {default:Postgres}=await import(pathToFileURL(require.resolve('embedded-postgres')));
const {Pool}=require('pg');
const root=resolve(process.argv[2] || fileURLToPath(new URL('..',import.meta.url)));
const base=process.argv.includes('--baseline');
const profile=process.argv.includes('--profile');
const scheduled=process.argv.includes('--scheduled');
const deadlineMigration=scheduled?await readFile(join(root,'recovery-finish.sql'),'utf8'):'';
const dir=await mkdtemp(join(tmpdir(),'dq-load-'));
const password=randomUUID();
const pg=new Postgres({databaseDir:join(dir,'db'),user:'postgres',password,port:18473,
  postgresFlags:['-k',dir,'-h','127.0.0.1'],persistent:false,autoRehydrateSymlinks:true,onLog:()=>{},onError:()=>{}});
const table='sefirot_december_quest_';
const first='2026-12-01T17:00:00Z',last='2026-12-03T17:00:00Z';
const schema=await readFile(join(root,'test/schema.sql'),'utf8');
const migration=await readFile(join(root,'persist.sql'),'utf8');
const feature=base?'':await readFile(join(root,'single-flight.sql'),'utf8');
const fixtures=[];
for(let h=0;h<26;h++)for(let a=h+1;a<26;a++)fixtures.push(['t'+h,'t'+a]);
const header='Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG';
function season(year) {
  const rows=[];
  for(let d=1;d<=20;d++)for(let t=0;t<26;t++)rows.push(['E0',d+'/11/'+year,'20:00','t'+t,'t'+((t+d)%26),d%4,t%3].join(','));
  return rows;
}
const prior=season(2025),current=season(2026);
let pool,server,stamp,size,counts,holdSource=false,seenSource,slowCalendar=false,dropAck=false;
const rpc={
  dq_predictor_run_state:['p_model_version'],dq_claim_predictor_run:['p_model_version'],
  dq_release_predictor_run:['p_token'],dq_finish_predictor_run:['p_token','p_run','p_forecasts','p_validation','p_settlements'],
  dq_finish_scheduled_predictor:['p_token','p_until','p_run','p_forecasts','p_validation','p_settlements'],
  dq_commit_predictor_run:['p_run','p_forecasts','p_validation','p_settlements'],
  dq_pending_predictor_snapshots:['p_fixture_keys','p_model_version']
};
async function http(req,res) {
  const path=new URL(req.url,'http://localhost').pathname;
  if(path.startsWith('/csv/')){
    counts.csv++;seenSource?.();
    if(holdSource)await delay(400);
    const isCurrent=path.includes('/2627/');
    const ft=stamp===last&&isCurrent?fixtures.slice(0,size).map(([h,a])=>['E0','01/12/2026','20:00',h,a,2,1].join(',')):[];
    res.end(path.endsWith('/fixtures.csv')?'Div,Date,Time,HomeTeam,AwayTeam\nE0,01/12/2026,20:00,X,Y':
      [header,...(isCurrent?current:prior),...ft].join('\n'));return;
  }
  counts.rest++;
  const dbStart=performance.now();
  const name=path.split('/').at(-1);
  let rows;
  if(name===table+'fixtures' && slowCalendar)await delay(250);
  if(name===table+'fixtures')rows=(await pool.query('select * from '+table+'fixtures order by kickoff,fixture_key limit 301')).rows;
  else {
    assert.ok(Object.hasOwn(rpc,name));
    req.setEncoding('utf8');
    let body='';for await(const chunk of req)body+=chunk;
    const data=JSON.parse(body);
    const values=rpc[name].map(k=>['p_run','p_forecasts','p_validation','p_settlements'].includes(k)?JSON.stringify(data[k]):data[k]);
    const fn='public.'+name+'('+values.map((_,i)=>'$'+(i+1)).join(',')+')';
    const query=name==='dq_pending_predictor_snapshots'?'select * from '+fn:'select '+fn+' as r';
    if(profile){
      const client=await pool.connect();
      try{
        await client.query('begin');
        const lockStart=performance.now();
        if(['dq_commit_predictor_run','dq_finish_predictor_run','dq_finish_scheduled_predictor'].includes(name))
          await client.query('select pg_advisory_xact_lock(721735,202612)');
        const sqlStart=performance.now();
        const result=await client.query(query,values);
        const commitStart=performance.now();
        await client.query('commit');
        counts.sql[name]={lock:sqlStart-lockStart,execution:commitStart-sqlStart,commit:performance.now()-commitStart};
        rows=name==='dq_pending_predictor_snapshots'?result.rows:result.rows[0].r;
      }catch(error){await client.query('rollback');throw error;}
      finally{client.release();}
    }else rows=name==='dq_pending_predictor_snapshots'?(await pool.query('select * from '+fn,values)).rows:
      (await pool.query('select '+fn+' as r',values)).rows[0].r;
  }
  counts.restHandlerMs+=Math.round(performance.now()-dbStart);
  if(dropAck && name==='dq_finish_predictor_run'){dropAck=false;res.destroy();return;}
  res.end(JSON.stringify(rows));
}
async function reset(n){
  stamp=first;size=n;
  await pool.query('drop schema public cascade; create schema public; grant usage on schema public to public');
  await pool.query("create table qa_clock(stamp timestamptz); create function qa_now() returns timestamptz language sql stable as 'select stamp from public.qa_clock'");
  await pool.query('insert into qa_clock values ($1)',[stamp]);
  await pool.query((schema.replace(/^create role .*;$/gm,'')+migration+feature+deadlineMigration).replaceAll('statement_timestamp()','public.qa_now()').replaceAll('clock_timestamp()','public.qa_now()'));
  await pool.query('insert into '+table+"fixtures(fixture_key,competition,home_team,away_team,kickoff,source_name,source_url,source_quality,timing_status,checked_at) select h||'-'||a,'EPL',h,a,'2026-12-01 20:00Z','local','https://example.invalid','official','confirmed',$3 from unnest($1::text[],$2::text[]) f(h,a)",[fixtures.slice(0,n).map(x=>x[0]),fixtures.slice(0,n).map(x=>x[1]),first]);
}
async function batch(n,timeoutCalendar=false){
  counts={csv:0,rest:0,restHandlerMs:0,...(profile?{sql:{}}:{})};
  const children=Array.from({length:n},()=>fork(fileURLToPath(new URL('cycle-worker.mjs',import.meta.url)),
    [root,'http://127.0.0.1:'+server.address().port,timeoutCalendar?'timeout':profile?'profile':'normal',scheduled?'scheduled':'default'],{stdio:['ignore','inherit','inherit','ipc']}));
  let timer, workersRssKiB=0;
  function sampleMemory(){
    let rss=0;
    for(const child of children){
      try{
        const status=readFileSync('/proc/'+child.pid+'/status','utf8');
        rss+=Number(status.match(/^VmRSS:\s+(\d+)/m)?.[1]||0);
      }catch(error){if(error.code!=='ENOENT')throw error;}
    }
    workersRssKiB=Math.max(workersRssKiB,rss);
  }
  try {
    await Promise.all(children.map(child=>once(child,'message',{signal:AbortSignal.timeout(30000)})));
    const results=children.map(child=>once(child,'message',{signal:AbortSignal.timeout(120000)}));
    sampleMemory();timer=setInterval(sampleMemory,25);
    const start=performance.now();
    for(const child of children)child.send(stamp);
    const messages=(await Promise.all(results)).map(([r])=>r);
    return {ms:Math.round(performance.now()-start),...counts,workersRssKiB,workerPeakKiB:Math.max(...messages.map(r=>r.rssKiB||0)),messages};
  } finally {clearInterval(timer);for(const child of children)child.kill();}
}
function summary(result){const {messages,...metrics}=result;return profile?{...metrics,...messages[0].profile}:metrics;}
try {
  await pg.initialise();await pg.start();
  pool=new Pool({host:'127.0.0.1',port:18473,user:'postgres',password,database:'postgres',max:24});
  await pool.query('create role anon;create role authenticated;create role service_role bypassrls');
  server=createServer((req,res)=>http(req,res).catch(error=>{res.statusCode=500;res.end(error.message);}));
  server.listen(0,'127.0.0.1');await once(server,'listening');
  for(const workers of (profile?[]:[2,5,10,20])){
    await reset(1);holdSource=true;
    const run=await batch(workers);
    assert.ok(run.messages.every(m=>!m.error),JSON.stringify(run.messages));
    assert.equal(run.csv,3*(base?workers:1));
    assert.equal((await pool.query('select count(*) from '+table+'auto_runs')).rows[0].count,'1');
    console.log(JSON.stringify({workers,...summary(run)}));
  }
  if(!base && !profile){
    await reset(1);
    const reached=new Promise(r=>{seenSource=r;});
    const child=fork(fileURLToPath(new URL('cycle-worker.mjs',import.meta.url)),
      [root,'http://127.0.0.1:'+server.address().port],{stdio:['ignore','inherit','inherit','ipc']});
    await once(child,'message');child.send(stamp);
    await Promise.race([reached,delay(5000).then(()=>{throw Error('worker never reached source');})]);
    const old=(await pool.query('select token,model_version,started_at from dq_predictor_leases')).rows[0];
    const exited=once(child,'exit');child.kill('SIGKILL');await exited;seenSource=null;
    const busy=await batch(1);
    assert.equal(busy.messages[0].result.skipped,'RUN_IN_PROGRESS');assert.equal(busy.csv,0);
    stamp='2026-12-01T17:10:00.987654Z';
    await pool.query('update qa_clock set stamp=$1',[stamp]);
    const replacement=(await pool.query('select dq_claim_predictor_run($1) r',[old.model_version])).rows[0].r;
    assert.ok(replacement.token);
    await pool.query('select dq_release_predictor_run($1)',[old.token]);
    await assert.rejects(pool.query("select dq_finish_predictor_run($1,$2,'[]','[]','[]')",
      [old.token,{model_version:old.model_version,started_at:old.started_at}]),/PREDICTOR_LEASE_LOST/);
    assert.equal((await pool.query('select token from dq_predictor_leases')).rows[0].token,replacement.token);
    // Rollback after a write error must also restore the deleted lease.
    const run={run_status:'OK',model_version:old.model_version,started_at:new Date(stamp).toISOString()};
    await assert.rejects(pool.query("select dq_finish_predictor_run($1,$2,'{}','[]','[]')",
      [replacement.token,run]),/array/);
    assert.equal((await pool.query('select token from dq_predictor_leases')).rows[0].token,replacement.token);
    await pool.query('select dq_release_predictor_run($1)',[replacement.token]);
    slowCalendar=true;
    const timeout=await batch(1,true);
    assert.match(timeout.messages[0].error,/timeout/i);assert.equal(timeout.csv,0);
    assert.equal((await pool.query('select count(*) from dq_predictor_leases')).rows[0].count,'0');
    slowCalendar=false;dropAck=true;
    const ambiguous=await batch(1);assert.ok(ambiguous.messages[0].error);
    const recovered=await batch(1);
    assert.equal(recovered.messages[0].result.skipped,'RECENT_SUCCESS_IN_CYCLE');assert.equal(recovered.csv,0);
    assert.equal((await pool.query('select count(*) from '+table+'auto_snapshots')).rows[0].count,'1');
    console.log('PASS SIGKILL, busy, expiry, stale finish/release, REST timeout, lost commit reply, one seal');
  }
  holdSource=false;
  for(const n of (profile?[300]:[1,100,300,301])){
    await reset(n);
    const forecast=await batch(1);
    if(n===301){assert.equal(forecast.messages[0].error,'FIXTURE_SOURCE_LIMIT');assert.equal(forecast.csv,0);continue;}
    assert.equal(forecast.messages[0].result?.sealed,n,JSON.stringify(forecast.messages));
    assert.equal(forecast.messages[0].result.modeled,n);
    const digest=async()=>{
      const rows=(await pool.query("select (to_jsonb(s)-'id')::text as seal from "+table+"auto_snapshots s order by fixture_key")).rows;
      const hash=createHash('sha256');
      for(const {seal} of rows){assert.ok(!seal.includes('�'));hash.update(seal+'\n');}
      return hash.digest('hex');
    };
    const sealed=await digest();
    const immutable=async()=>(await pool.query("select md5(string_agg(to_jsonb(s)::text,'' order by fixture_key)) as d from "+table+"auto_snapshots s")).rows[0].d;
    const allFields=await immutable();
    stamp=last;await pool.query('update qa_clock set stamp=$1',[stamp]);
    const settlement=await batch(1);
    assert.equal(settlement.messages[0].result?.settled,n,JSON.stringify(settlement.messages));
    assert.equal(await immutable(),allFields);
    console.log(JSON.stringify({fixtures:n,forecast:summary(forecast),settlement:summary(settlement),sealHash:sealed}));
  }
} finally {
  if(server)await new Promise(r=>server.close(r));
  if(pool){
    await pool.end();
    // Some pg clients report the local server's shutdown after the pool has ended.
    pool.on('error',error=>{if(error.code!=='57P01')throw error;});
  }
  await pg.stop();await rm(dir,{recursive:true,force:true});
}
