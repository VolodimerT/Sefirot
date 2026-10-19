/* Isolated PostgreSQL WASM proof; no hosted writes or provider calls. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {PGlite} from '@electric-sql/pglite';
import {createStoreHandler} from '../server/chat_store_gateway.js';
const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const inside=s=>s.replace(/^begin;\s*$/m,'').replace(/^commit;\s*$/m,'');
const pg=new PGlite();let groups=0;
try {
 await pg.exec(read('tests/fixtures/chat_bridge_legacy.sql'));
 await pg.exec(read('tests/fixtures/probe_rollout_legacy.sql'));
 await pg.exec('create table sefirot_budget_private.sports_attempt(started_at timestamptz)');
 const up=inside(read('supabase/migrations/20261017173910_sports_source_archive.sql'));
 const budget=(await pg.query('select * from sefirot_budget_private.sports_budget')).rows;
 await pg.exec('begin');await pg.exec(up);await pg.exec('commit');groups++;
 await pg.exec('begin');await pg.exec(read('tests/fixtures/football_source_cases.sql'));await pg.exec('rollback');
 const status=async()=>(await pg.query('select public.sefirot_source_status() v')).rows[0].v;
 assert.equal((await status()).ready,false);
 await pg.exec('set role service_role');
 await assert.rejects(pg.exec("select public.sefirot_source_export('')"),/permission denied/);
 await pg.exec('reset role');groups++;
 const id='00000000-0000-0000-0000-000000000088';
 await pg.query("insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts,submitted_at) values($1,'sports_probe',$2,'ERROR',1,'2026-01-01Z')",[id,{queries:[{endpoint:'fixtures',params:{league:39,season:2026}}]}]);
 const data={get:'fixtures',parameters:{league:'39',season:'2026'},errors:[],results:0,paging:{current:1,total:1},response:[]};
 const packet={data,receipt:{provider:'API_FOOTBALL_V3',provider_host:'v3.football.api-sports.io',transport:'SUPABASE_GATEWAY',endpoint:'/fixtures',parameters:{league:39,season:2026},sports_only:true,http_status:200,request_started_at:'2026-02-01Z',upstream_received_at:'2026-02-01Z',received_at:'2026-02-01Z',payload_hash:'a'.repeat(64)}};
 const hash=s=>createHash('sha256').update(s).digest('hex');
 const append=async(raw,job=id,attempt=1)=>pg.query('select public.sefirot_source_append($1,$2,$3,$4) v',[raw,hash(raw),job,attempt]);
 const raw=JSON.stringify(packet);await append(raw);await append(raw);groups++;
 assert.equal((await pg.query('select count(*)::int n from sefirot.sports_archive')).rows[0].n,1);
 await assert.rejects(append(raw,id,2),/SOURCE_JOB_BINDING_REQUIRED/);
 await assert.rejects(append(raw.replace('"data":','"data":{},"data":')),/SOURCE_DUPLICATE_JSON_KEY/);
 await assert.rejects(append(JSON.stringify({...packet,token:'SYNTHETIC'})),/SOURCE_PACKET_REJECTED/);
 await assert.rejects(append(JSON.stringify({...packet,receipt:{...packet.receipt,quota:{token:'SYNTHETIC'}}})),/SOURCE_PACKET_REJECTED/);groups++;
 await assert.rejects(append(JSON.stringify({...packet,receipt:{...packet.receipt,quota:{'A P I K E Y':'SYNTHETIC_PRIVATE'}}})),/SOURCE_UNSAFE_JSON_KEY/);
 await assert.rejects(pg.exec('delete from sefirot.sports_archive'),/SOURCE_ARCHIVE_IMMUTABLE/);
 await pg.exec('grant execute on function public.sefirot_source_begin(uuid,integer,text,jsonb),public.sefirot_source_append(text,text,uuid,integer),public.sefirot_source_export(text) to service_role');
 await pg.query("update sefirot.chat_bridge_jobs set status='RUNNING' where id=$1",[id]);
 await pg.exec('set role service_role');assert.equal((await status()).ready,true);
 await pg.query('select public.sefirot_source_begin($1,1,$2,$3)',[id,'fixtures',{league:39,season:2026}]);
 await assert.rejects(pg.query('select public.sefirot_source_begin($1,1,$2,$3)',[id,'fixtures',{league:39,season:2026}]),/SOURCE_DISPATCH_ALREADY_ATTEMPTED/);
 const exported=(await pg.query("select public.sefirot_source_export('') v")).rows[0].v;
 assert.equal(exported.raw_source,raw);assert.equal(exported.raw_sha256,hash(raw));
 const token='SYNTHETIC_ARCHIVE_RELAY_TOKEN_000000000000000000000000';
 const relay=createStoreHandler({credentialHashes:[hash(token)],env:n=>n==='SUPABASE_URL'?'https://private.invalid':'SYNTHETIC_SERVICE',
  fetcher:async(url,options)=>{assert.equal(url,'https://private.invalid/rest/v1/rpc/sefirot_source_export');
    const a=JSON.parse(options.body);return Response.json((await pg.query('select public.sefirot_source_export($1) v',[a.p_after])).rows[0].v);}});
 const body=JSON.stringify({action:'source_export',after:''});
 const out=await relay(new Request('https://relay.invalid',{method:'POST',headers:{'x-sefirot-bridge-store-token':token,'content-length':String(Buffer.byteLength(body))},body}));
 assert.equal(out.status,200);assert.equal((await out.json()).data.raw_source,raw);
 await assert.rejects(pg.exec('select * from sefirot.sports_archive'),/permission denied/);
 await assert.rejects(pg.exec('select public.sefirot_plan_collection_day()'),/permission denied/);
 await pg.exec('reset role');groups++;
 // An uncertain historical terminal job without a matching source prevents refetch.
 await pg.exec("update sefirot.chat_bridge_jobs set request='{\"queries\":[{\"endpoint\":\"fixtures\",\"params\":{\"league\":40,\"season\":2026}}]}' where id='00000000-0000-0000-0000-000000000070'");
 assert.equal((await pg.query('select public.sefirot_plan_collection_day(40,2026) v')).rows[0].v.queued,0);
 await pg.query("update sefirot.chat_bridge_jobs set status='DONE' where id=$1",[id]);
 assert.equal((await pg.query('select public.sefirot_plan_collection_day(39,2026) v')).rows[0].v.queued,1);
 assert.equal((await pg.query('select public.sefirot_plan_collection_day(39,2026) v')).rows[0].v.queued,0);
 await pg.exec('insert into sefirot_budget_private.sports_attempt select clock_timestamp() from generate_series(1,5)');
 assert.equal((await pg.query('select public.sefirot_plan_collection_day(41,2026) v')).rows[0].v.reason,'DAILY_FIVE_ATTEMPT_CAP');
 assert.deepEqual((await pg.query('select * from sefirot_budget_private.sports_budget')).rows,budget);groups++;
 // Native CI also exercises the same migration on PostgreSQL17 via its owned fixture.
 console.log(JSON.stringify({groups,source:'SYNTHETIC_ONLY'}));
} finally {await pg.close();}
