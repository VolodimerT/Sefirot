import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { columns, fixture, form, freeze, tablePrefix, weekly } from './acceptance.mjs';

const qaClock = '2026-12-01T17:00:00Z';
const cronToken = 'a'.repeat(64);
const testRoleToken = 'qa-local-rest';
const db = new PGlite();
const flags = { currentFileAttempts:0 };
const rows = async (sql,params) => (await db.query(sql,params)).rows;
let server, deno;

try {
  const schema = await readFile(new URL('./schema.sql',import.meta.url),'utf8');
  const migration = await readFile(new URL('../persist.sql',import.meta.url),'utf8');
  await db.exec('create function public.dq_test_clock() returns timestamptz language sql stable as '
    +"$$select '2026-12-01T17:00:00Z'::timestamptz$$");
  await db.exec(freeze(schema));
  await db.exec(freeze(migration));
  await db.query('insert into '+tablePrefix+'fixtures '
    +'(fixture_key,competition,home_team,away_team,kickoff,source_name,source_url,source_quality,timing_status,checked_at) '
    +'values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)',
    [fixture.fixture_key,fixture.competition,fixture.home_team,fixture.away_team,fixture.kickoff,
      'synthetic',fixture.source_url,fixture.source_quality,fixture.timing_status,fixture.checked_at]);

  server = createServer(async (request,response) => {
    const pathname = new URL(request.url,'http://127.0.0.1').pathname;
    const send = (status,value) => {
      response.writeHead(status,{'Content-Type':'application/json'});
      response.end(JSON.stringify(value));
    };
    try {
      if (pathname.startsWith('/source/')) {
        const current = pathname.endsWith('/2627/E0.csv');
        if (current && flags.currentFileAttempts++ === 0) return send(503,{error:'QA_TRANSIENT'});
        const history = current ? form : form.map(line=>line.replace('/2026,','/2025,'));
        response.writeHead(200,{'Content-Type':'text/csv'});
        return response.end(pathname.endsWith('/fixtures.csv') ? weekly : [columns,...history].join('\n'));
      }
      if (request.headers.apikey !== testRoleToken) return send(401,{error:'MOCK_ROLE_DENIED'});
      const resource = pathname.replace('/rest/v1/','');
      if (resource === tablePrefix+'auto_runs' || resource === tablePrefix+'fixtures') {
        return send(200,await rows('select * from '+resource));
      }
      let raw = '';
      for await (const chunk of request) raw += chunk;
      const payload = JSON.parse(raw);
      if (resource === 'rpc/dq_predictor_cron_authorized') return send(200,payload.p_token === cronToken);
      assert.equal(resource,'rpc/dq_commit_predictor_run');
      await db.exec('set role service_role');
      try {
        const [result] = await rows('select public.dq_commit_predictor_run($1,$2,$3,$4) as report',
          [payload.p_run,payload.p_forecasts,payload.p_validation,payload.p_settlements].map(value=>JSON.stringify(value)));
        return send(200,result.report);
      } finally { await db.exec('reset role'); }
    } catch (error) {
      return send(500,{error:error.message});
    }
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const restAddress = 'http://127.0.0.1:'+server.address().port;
  const env = {PATH:process.env.PATH,DQ_QA_REST:restAddress,SUPABASE_URL:restAddress,
    SUPABASE_SERVICE_ROLE_KEY:testRoleToken,DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN:''};
  deno = spawn(process.env.DQ_QA_DENO_BIN || 'deno',
    ['run','--quiet','--allow-env=DQ_QA_REST,SUPABASE_URL,SUPABASE_SERVICE_ROLE_KEY,DQ_AUTHORIZED_GATEWAY_RUNNER_TOKEN',
      '--allow-net=127.0.0.1',fileURLToPath(new URL('./edge-entry.mjs',import.meta.url))],
    {env,stdio:['ignore','pipe','inherit']});
  const lines = createInterface({input:deno.stdout});
  let timer;
  const denoPort = await new Promise((resolve,reject) => {
    deno.once('error',reject);
    deno.once('exit',code=>reject(Error('Deno exited before ready: '+code)));
    lines.on('line',line=>{ if (/^DQ_PORT=\d+$/.test(line)) resolve(Number(line.slice(8))); });
    timer=setTimeout(()=>reject(Error('Deno start timed out')),10000);
  }).finally(()=>clearTimeout(timer));
  const address = 'http://127.0.0.1:'+denoPort;
  const request = async (method,token) => {
    const headers = token ? {'x-dq-predictor-token':token} : {};
    const response = await fetch(address,{method,headers,signal:AbortSignal.timeout(15000)});
    return {status:response.status,body:await response.json()};
  };
  const health = await request('GET');
  assert.equal(health.status,200);
  assert.equal(health.body.betting_enabled,false);
  assert.equal((await request('POST')).status,401);
  assert.equal((await request('POST','b'.repeat(64))).status,401);
  const first = await request('POST',cronToken);
  assert.equal(first.status,200,JSON.stringify(first.body));
  assert.equal(first.body.modeled,1);
  assert.equal(first.body.sealed,1);
  assert.equal(first.body.pass,1);
  assert.equal(first.body.wagers_executed,0);
  assert.equal(flags.currentFileAttempts,2);
  assert.equal((await request('POST',cronToken)).body.skipped,'RUN_WITHIN_SIX_HOURS');
  const seals = await rows('select * from '+tablePrefix+'auto_snapshots');
  assert.equal(seals.length,1);
  assert.equal(seals[0].generated_at.toISOString(),new Date(qaClock).toISOString());
  assert.equal(seals[0].evidence.decision.verdict,'пропуск');
  console.log('PASS: HTTP Deno, ACL, one 503 retry, one compatible seal and idempotent rerun');
} finally {
  if (deno?.pid && deno.exitCode===null && deno.signalCode===null) {
    const exited = once(deno,'exit');
    deno.kill();
    await exited;
  }
  if (server?.listening) {
    server.closeAllConnections();
    await new Promise(resolve=>server.close(resolve));
  }
  await db.close();
}
