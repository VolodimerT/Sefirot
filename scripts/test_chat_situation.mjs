/* Synthetic SQL/auth/lease tests on actual PostgreSQL WASM, no cloud access. */
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createInterface} from "node:readline";
import {PGlite} from "@electric-sql/pglite";
import {createStoreHandler} from "../server/chat_store_gateway.js";

const TOKEN="synthetic-store-token-for-local-tests-only-000000000000000000";
const SERVICE="synthetic-service-role";
const baseSQL=`
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
`;
const extensionSQL=await readFile(new URL("../schema/supabase_chat_situation.sql",import.meta.url),"utf8");
const callSQL={
 sefirot_chat_claim:["select public.sefirot_chat_claim() value",[]],
 sefirot_bridge_pull:["select public.sefirot_bridge_pull() value",[]],
 sefirot_bridge_save:["select public.sefirot_bridge_save($1,$2,$3) value",["p_revision","p_snapshot","p_checksum"]],
 sefirot_chat_complete:["select public.sefirot_chat_complete($1,$2,$3,$4) value",["p_id","p_success","p_response","p_error"]],
 sefirot_situation_enqueue:["select public.sefirot_situation_enqueue($1) value",["p_request"]],
 sefirot_situation_source:["select public.sefirot_situation_source($1) value",["p_receipt_id"]],
 sefirot_situation_complete:["select public.sefirot_situation_complete($1,$2,$3,$4,$5) value",["p_id","p_attempt","p_success","p_response","p_error"]]
};

async function rpc(pg,name,args={}) {
 const [sql,keys]=callSQL[name]??[];if(!sql)throw new Error("RPC_NOT_ALLOWED");
 const vals=keys.map(k=>args[k]??null);
 return (await pg.query(sql,vals)).rows[0].value;
}
const valid={fixture_id:"synthetic:fixture:123",provider_status:"NS",kickoff:"2030-01-01T14:00:00+00:00",
 status_observed_at:"2030-01-01T11:59:58+00:00",request_at:"2030-01-01T12:00:00+00:00",
 intent:"auto",depth:"auto",original_provider_receipt_id:"a".repeat(64),
 identity:{source_id:"synthetic-source",source_revision:1,receipt_hash:"a".repeat(64),model_hash:"b".repeat(64)}};
function result(q) {return {schema:"sefirot-situation-status-v1",fixture_id:q.fixture_id,
 original_provider_receipt_id:q.original_provider_receipt_id,source_identity:structuredClone(q.identity),
 request_at:q.request_at,monetary_permission:false,core_invoked:false,execution_enabled:false,
 prematch_core_allowed:false,live_betting_allowed:false,external_origin_verified:false};}

async function sqlTests() {
 const pg=new PGlite();let groups=0;
 try {
  await pg.exec(baseSQL);await pg.exec(extensionSQL);groups++;
  const first=await rpc(pg,"sefirot_situation_enqueue",{p_request:valid});
  const second=await rpc(pg,"sefirot_situation_enqueue",{p_request:structuredClone(valid)});
  assert.equal(first.job_id,second.job_id);assert.equal(second.reused,true);groups++;
  const offsets={...valid,kickoff:"2030-01-01T16:00:00+02:00",request_at:"2030-01-01T14:00:00+02:00",
    status_observed_at:"2030-01-01T13:59:58+02:00"};
  assert.equal((await rpc(pg,"sefirot_situation_enqueue",{p_request:offsets})).job_id,first.job_id);
  const alternate=await rpc(pg,"sefirot_situation_enqueue",{p_request:{...valid,depth:"fast"}});
  assert.notEqual(first.job_id,alternate.job_id);groups++;
  for(const value of [{...valid,monetary_permission:true},{...valid,identity:{...valid.identity,source_revision:true}},
    {...valid,kickoff:"2030-01-01T14:00:00"},{...valid,identity:{...valid.identity,receipt_hash:"c".repeat(64)}},
    {...valid,provider_status:null},{...valid,identity:null},{...valid,intent:"bet"}])
   await assert.rejects(rpc(pg,"sefirot_situation_enqueue",{p_request:value}));
  groups++;
  // Old kinds remain accepted, old completion retains its existing shape.
  const old="00000000-0000-0000-0000-000000000001";
  await pg.query("insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts,submitted_at) values($1,'status','{}','RUNNING',1,now()-interval '1 hour')",[old]);
  assert.equal((await rpc(pg,"sefirot_chat_complete",{p_id:old,p_success:true,p_response:{stage:"READY"},p_error:null})).completed,true);groups++;
  let job=(await rpc(pg,"sefirot_chat_claim")).job;
  const q=job.request;
  await assert.rejects(rpc(pg,"sefirot_chat_complete",{p_id:job.id,p_success:true,p_response:result(q),p_error:null}),/SITUATION_LEASE_REQUIRED/);groups++;
  await pg.query("update sefirot.chat_bridge_jobs set claimed_at=now()-interval '4 minutes' where id=$1",[job.id]);
  let reclaimed=(await rpc(pg,"sefirot_chat_claim")).job;
  assert.equal(reclaimed.id,job.id);assert.equal(reclaimed.attempt,2);
  await assert.rejects(rpc(pg,"sefirot_situation_complete",{p_id:job.id,p_attempt:1,p_success:true,p_response:result(q),p_error:null}),/STALE_SITUATION_LEASE/);groups++;
  const done={p_id:job.id,p_attempt:2,p_success:true,p_response:result(q),p_error:null};
  assert.equal((await rpc(pg,"sefirot_situation_complete",done)).completed,true);
  assert.equal((await rpc(pg,"sefirot_situation_complete",done)).completed,true);groups++;
  await assert.rejects(rpc(pg,"sefirot_situation_complete",{...done,p_response:{...result(q),fixture_id:"foreign"}}));groups++;
  for(const [field,value] of [["source_id","foreign"],["source_revision",2],
    ["receipt_hash","c".repeat(64)],["model_hash","d".repeat(64)]]) {
   const foreign=result(q);foreign.source_identity[field]=value;
   await assert.rejects(rpc(pg,"sefirot_situation_complete",{...done,p_response:foreign}),/INVALID_SITUATION_RESPONSE/);
  } groups++;
  await assert.rejects(rpc(pg,"sefirot_situation_complete",{...done,p_response:{...result(q),request_at:"2030-01-01T12:01:00+00:00"}}),/INVALID_SITUATION_RESPONSE/);
  await assert.rejects(rpc(pg,"sefirot_situation_complete",{...done,p_error:"CONTRADICTORY_SUCCESS"}),/INVALID_SITUATION_RESPONSE/);groups++;
  for(const field of ["prematch_core_allowed","live_betting_allowed","external_origin_verified"])
   await assert.rejects(rpc(pg,"sefirot_situation_complete",{...done,p_response:{...result(q),[field]:true}}),/INVALID_SITUATION_RESPONSE/);
  groups++;
  const probe="00000000-0000-0000-0000-000000000002";
  await pg.query("insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values($1,'sports_probe','{}','RUNNING',1)",[probe]);
  assert.equal((await rpc(pg,"sefirot_chat_complete",{p_id:probe,p_success:true,p_response:{sports_only:true},p_error:null})).completed,true);groups++;
  job=(await rpc(pg,"sefirot_chat_claim")).job;
  await assert.rejects(rpc(pg,"sefirot_situation_complete",{p_id:job.id,p_attempt:1,p_success:true,p_response:{...result(job.request),monetary_permission:true},p_error:null}));groups++;
  assert.equal((await rpc(pg,"sefirot_situation_source",{p_receipt_id:"a".repeat(64)})).receipt,null);
  await pg.query("insert into sefirot.chat_situation_receipts(receipt_id,envelope) values($1,$2)",["a".repeat(64),{body:{origin:"SYNTHETIC_TEST_ONLY"},collector_signature:"synthetic"}]);
  await assert.rejects(pg.query("update sefirot.chat_situation_receipts set envelope='{}'"),/APPEND_ONLY/);
  await assert.rejects(pg.query("delete from sefirot.chat_situation_receipts"),/APPEND_ONLY/);groups++;
  for(const role of ["anon","authenticated"]) {
   await pg.exec(`set role ${role}`);
   for(const name of ["sefirot_situation_enqueue","sefirot_situation_source","sefirot_situation_complete"])
    await assert.rejects(rpc(pg,name,name.endsWith("enqueue")?{p_request:valid}:{}),/permission denied/);
   await pg.exec("reset role");
  } groups++;
  await pg.exec("set role service_role");
  assert.equal((await rpc(pg,"sefirot_situation_enqueue",{p_request:valid})).reused,true);
  await assert.rejects(pg.query("select * from sefirot.chat_situation_receipts"),/permission denied/);
  await pg.exec("reset role");groups++;
  const catalog=(await pg.query("select relrowsecurity from pg_class where relname='chat_situation_receipts'")).rows;
  assert.equal(catalog[0].relrowsecurity,true);
  assert.deepEqual((await pg.query("select * from sefirot.predictions")).rows,[{id:"canonical-untouched",payload:{sealed:true}}]);groups++;
 } finally {await pg.close();}
 return groups;
}

async function gatewayTests() {
 let calls=0;const hashes=[createHash("sha256").update(TOKEN).digest("hex")];
 const env=n=>({SUPABASE_URL:"https://synthetic.test",SUPABASE_SERVICE_ROLE_KEY:SERVICE})[n];
 const req=(body,token=TOKEN)=>{const raw=JSON.stringify(body);return new Request("https://synthetic.test",{
  method:"POST",headers:{"x-sefirot-bridge-store-token":token,"content-length":String(Buffer.byteLength(raw))},body:raw});};
 let upstream=Response.json({receipt:null});
 const handler=createStoreHandler({credentialHashes:hashes,env,fetcher:async(url,opts)=>{
  calls++;assert.equal(opts.redirect,"error");assert.equal(opts.headers.authorization,"Bearer "+SERVICE);
  return upstream;
 }});let groups=0;
 assert.equal((await handler(req({action:"situation_source",receipt_id:"a".repeat(64)},"wrong"))).status,401);
 assert.equal(calls,0);groups++;
 assert.equal((await createStoreHandler({env,fetcher:()=>{throw new Error("MUST_NOT_FETCH");}})(req({action:"pull"}))).status,401);groups++;
 assert.equal((await handler(req({action:"situation_source",receipt_id:"a".repeat(64)}))).status,200);groups++;
 assert.equal((await handler(req({action:"situation_source",receipt_id:"../secret"}))).status,422);
 assert.equal((await handler(req({action:"situation_source",receipt_id:"a".repeat(64),monetary_permission:true}))).status,422);groups++;
 upstream=Response.json({completed:true});
 assert.equal((await handler(req({action:"complete",id:"00000000-0000-0000-0000-000000000001",attempt:2,success:true,response:{},error:null}))).status,200);groups++;
 upstream=Response.json({revision:1});assert.equal((await handler(req({action:"pull"}))).status,200);groups++;
 upstream=Response.json({job:null});assert.equal((await handler(req({action:"claim"}))).status,200);groups++;
 const limited=createStoreHandler({credentialHashes:hashes,env,fetcher:async()=>new Response("rate",{status:429})});
 assert.equal((await limited(req({action:"pull"}))).status,503);groups++;
 const failed=createStoreHandler({credentialHashes:hashes,env,fetcher:async()=>{throw new Error("private upstream");}});
 const failure=await failed(req({action:"pull"}));assert.equal(failure.status,503);assert(!JSON.stringify(await failure.json()).includes("private upstream"));groups++;
 upstream=Response.json({secret:"private"});assert.equal((await handler(req({action:"situation_source",receipt_id:"a".repeat(64)}))).status,502);groups++;
 const timeout=createStoreHandler({credentialHashes:hashes,env,timeoutMs:10,fetcher:(_,opts)=>new Promise((_,reject)=>opts.signal.addEventListener("abort",()=>reject(new Error("TIMEOUT")),{once:true}))});
 assert.equal((await timeout(req({action:"pull"}))).status,503);groups++;
 for(const url of ["http://synthetic.test","https://user:password@synthetic.test",
   "https://synthetic.test/path","https://synthetic.test?override=1",
   "https://synthetic.test#override","https://synthetic.test:8443","not-a-url"]) {
  let sent=false;
  const invalid=createStoreHandler({credentialHashes:hashes,
    env:n=>({SUPABASE_URL:url,SUPABASE_SERVICE_ROLE_KEY:SERVICE})[n],
    fetcher:async()=>{sent=true;throw new Error("MUST_NOT_FETCH");}});
  assert.equal((await invalid(req({action:"pull"}))).status,503);assert.equal(sent,false);
 } groups++;
 return groups;
}

async function serve() {
 let pg=new PGlite(process.argv[3]);await pg.exec(baseSQL);await pg.exec(extensionSQL);
 let port;const calls=[];
 const handler=createStoreHandler({credentialHashes:[createHash("sha256").update(TOKEN).digest("hex")],
  env:n=>({SUPABASE_URL:"https://synthetic.test",SUPABASE_SERVICE_ROLE_KEY:SERVICE})[n],
  // Test-only mapping of a validated HTTPS RPC URL onto this owned loopback server.
  fetcher:(url,opts)=>fetch("http://127.0.0.1:"+port+new URL(url).pathname,opts)});
 const server=createServer(async(incoming,out)=>{
  try {
   const chunks=[];let size=0;for await(const part of incoming){size+=part.length;if(size>2900000)throw new Error("SIZE");chunks.push(part);}
   const raw=Buffer.concat(chunks);let response;
   if(incoming.url==="/functions/v1/sefirot-chat-store") {
    response=await handler(new Request("http://127.0.0.1:"+port+incoming.url,{method:incoming.method,headers:incoming.headers,body:raw}));
   } else if(incoming.url.startsWith("/rest/v1/rpc/")&&incoming.headers.authorization==="Bearer "+SERVICE) {
    const name=incoming.url.split("/").at(-1);calls.push(name);
    try {response=Response.json(await rpc(pg,name,JSON.parse(raw)));}
    catch {response=Response.json({error:"RPC_REJECTED"},{status:400});}
   } else {response=new Response("denied",{status:401});}
   out.writeHead(response.status,Object.fromEntries(response.headers));out.end(Buffer.from(await response.arrayBuffer()));
  } catch {out.writeHead(503);out.end("unavailable");}
 });
 await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));port=server.address().port;
 console.log(JSON.stringify({ready:true,port}));
 const lines=createInterface({input:process.stdin});
 for await(const line of lines) {
  try {
   const body=JSON.parse(line);let value;
   if(body.command==="enroll") {
    await pg.query("insert into sefirot.chat_situation_receipts(receipt_id,envelope) values($1,$2)",[body.request.original_provider_receipt_id,body.envelope]);
    value=await rpc(pg,"sefirot_situation_enqueue",{p_request:body.request});
   } else if(body.command==="read") {
    value=(await pg.query("select status,attempts,response,error from sefirot.chat_bridge_jobs where id=$1",[body.id])).rows[0];
   } else if(body.command==="restart") {
    await pg.close();pg=new PGlite(process.argv[3]);await pg.waitReady;value={restarted:true};
   } else if(body.command==="enqueue") value=await rpc(pg,"sefirot_situation_enqueue",{p_request:body.request});
   else if(body.command==="calls") value=calls.slice();
   else if(body.command==="close") {
    await pg.close();server.closeIdleConnections();await new Promise(resolve=>server.close(resolve));
    lines.close();process.stdin.pause();console.log(JSON.stringify({closed:true}));return;
   }
   else throw new Error("INVALID_CONTROL");
   console.log(JSON.stringify({value}));
  } catch(error){console.log(JSON.stringify({error:String(error)}));}
 }
 await pg.close();server.close();
}

try {
 if(process.argv[2]==="--serve") await serve();
 else console.log(JSON.stringify({sql_groups:await sqlTests(),gateway_groups:await gatewayTests(),source:"SYNTHETIC_ONLY"}));
} catch(error) {
 console.error(JSON.stringify({error:error.message,code:error.code,position:error.position,where:error.where}));
 process.exitCode=1;
}
