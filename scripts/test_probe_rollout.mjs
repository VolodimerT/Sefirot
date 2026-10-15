/* Offline upgrade/park proof using owned SQL fixtures, never cloud access. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
const read=p=>readFile(new URL('../'+p,import.meta.url),'utf8');
const manifest=JSON.parse(await read('schema/probe_rollout_manifest.json'));
const base=await read('tests/fixtures/chat_bridge_legacy.sql');
const legacy=await read('tests/fixtures/probe_rollout_legacy.sql');
const up=await read(manifest.up),park=await read(manifest.park);
const checks=JSON.parse(await read('tests/fixtures/probe_rollout_rejections.json'));
const assertions=await read('tests/fixtures/probe_rollout_assertions.sql');
const probeCases=await read('tests/fixtures/probe_completion_cases.sql');
const candidate=await read('schema/supabase_chat_situation.sql');
const inside=sql=>sql.replace(/^begin;\s*$/mi,'').replace(/^commit;\s*$/mi,'');
const bodyHash=sql=>createHash('sha256').update(sql).digest('hex');
const completeBody=(await read('schema/supabase_chat_situation.sql')).match(/create function public\.sefirot_probe_complete\([\s\S]*?as \$\$([\s\S]*?)\$\$;/)[1];
const fnState=async pg=>(await pg.query("select p.proname,p.prosrc,p.proacl::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','sefirot') and p.proname in ('sefirot_chat_complete','sefirot_chat_claim','sefirot_probe_complete','chat_complete_before_probe_fence') order by p.proname")).rows;
const claimed=async pg=>(await pg.query("select public.sefirot_chat_claim() value")).rows[0].value;
async function rejectGuard(pg,c) {
 await pg.exec('savepoint fault');
 try {
  await pg.exec(c.mutate);const before=await fnState(pg);
  await pg.exec('savepoint apply');
  await assert.rejects(pg.exec(inside(up)),new RegExp(c.error));
  await pg.exec('rollback to savepoint apply');
  assert.deepEqual(await fnState(pg),before); // Failed DDL never changes RPCs.
 } finally {await pg.exec('rollback to savepoint fault; release savepoint fault');}
}

export async function probeRolloutTests() {
 assert.equal(bodyHash(completeBody),manifest.probe_body_sha256);
 const pg=new PGlite();let groups=0;
 try {
  await pg.exec('begin');await pg.exec(base);await pg.exec(legacy);
  for(const c of checks.filter(c=>!c.after_upgrade)){await rejectGuard(pg,c);groups++;}
  const before=await fnState(pg);await pg.exec('savepoint interrupted');
  await assert.rejects(pg.exec(inside(up)+"\ndo $$ begin raise exception 'SYNTHETIC_INTERRUPTED';end $$;"),/SYNTHETIC_INTERRUPTED/);
  await pg.exec('rollback to savepoint interrupted; release savepoint interrupted');
  assert.deepEqual(await fnState(pg),before);groups++;
  await pg.exec(inside(up));
  const backup=(await fnState(pg)).find(f=>f.proname==='chat_complete_before_probe_fence');
  assert.equal((await pg.query("select has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE') allowed")).rows[0].allowed,false);
  assert.equal(backup.prosrc,before.find(f=>f.proname==='sefirot_chat_complete').prosrc);
  assert.equal(bodyHash((await fnState(pg)).find(f=>f.proname==='sefirot_probe_complete').prosrc),manifest.probe_body_sha256);groups++;
  const after=await fnState(pg);await pg.exec(inside(up));assert.deepEqual(await fnState(pg),after);groups++;
  for(const c of checks.filter(c=>!c.before_upgrade_only)){await rejectGuard(pg,c);groups++;}
  await pg.exec(assertions);await pg.exec(probeCases);
  assert.equal((await pg.query('select count(*)::int n from public.probe_test_cases')).rows[0].n,10);groups++;
  await pg.exec(inside(park));await pg.exec(inside(park));
  await pg.exec('savepoint denied_claim');await pg.exec('set role service_role');
  await assert.rejects(claimed(pg),/permission denied/);
  await pg.exec('rollback to savepoint denied_claim;release savepoint denied_claim');
  await pg.exec('select public.assert_probe_rollout_originals()');groups++;
  // Old worker cannot claim anything; legacy completion still cannot bypass the fence.
  await pg.exec("insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values('00000000-0000-0000-0000-000000000074','sports_probe','{}','RUNNING',1)");
  await pg.exec('savepoint denied_legacy');
  await assert.rejects(pg.query("select public.sefirot_chat_complete('00000000-0000-0000-0000-000000000074',false,null,'RESEARCH_RUNNER_ERROR')"),/PROBE_LEASE_REQUIRED/);
  await pg.exec('rollback to savepoint denied_legacy;release savepoint denied_legacy');
  await pg.exec("delete from sefirot.chat_bridge_jobs where id='00000000-0000-0000-0000-000000000074'");groups++;
  await pg.exec(inside(up));
  assert.equal((await pg.query("select has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE') allowed")).rows[0].allowed,false);groups++;
  await pg.exec('rollback');
 } finally {await pg.close();}
 // Applying the full package would lose an existing production kind.
 const populated=new PGlite();
 try {
  await populated.exec(base);await populated.exec(legacy);
  await populated.exec("insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values('00000000-0000-0000-0000-000000000075','stake_snapshot','{}','DONE',1)");
  await assert.rejects(populated.exec(candidate),/chat_bridge_jobs_kind_check/);await populated.exec('rollback');
  await populated.exec(up);
  assert.equal((await populated.query("select count(*)::int n from sefirot.chat_bridge_jobs where kind='stake_snapshot'")).rows[0].n,1);groups++;
 } finally {await populated.close();}
 // The same delta also works after the unified fresh-schema package.
 const fresh=new PGlite();
 try {
  await fresh.exec(base);await fresh.exec(legacy);await fresh.exec(candidate);await fresh.exec(up);
  assert.equal(bodyHash((await fnState(fresh)).find(f=>f.proname==='sefirot_probe_complete').prosrc),manifest.probe_body_sha256);groups++;
 } finally {await fresh.close();}
 return groups;
}

if(process.argv[1]&&new URL(import.meta.url).pathname.endsWith(process.argv[1].replaceAll('\\','/'))) {
 try {console.log(JSON.stringify({rollout_groups:await probeRolloutTests(),source:'SYNTHETIC_ONLY'}));}
 catch(e){console.error(JSON.stringify({error:e.message,code:e.code,where:e.where}));process.exitCode=1;}
}
