/* Disposable SQL verification of SEFIROT API-Football Pro 7500/day policy.
 * Never touches hosted Supabase or makes provider calls.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {PGlite} from '@electric-sql/pglite';
const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const pg=new PGlite();
try{
 await pg.exec('create role anon; create role authenticated; create role service_role bypassrls;');
 await pg.exec('create schema sefirot;');
 await pg.exec('create table sefirot.chat_bridge_jobs(id uuid primary key,kind text,status text,attempts integer default 0,request jsonb,submitted_at timestamptz default clock_timestamp(),completed_at timestamptz,response jsonb);');
 await pg.exec(read('server/migrations/20261012_shared_sports_budget.sql'));
 await pg.exec(read('supabase/migrations/20261015_research_api_budget_operator.sql'));
 await pg.exec(read('supabase/migrations/20261018172000_expand_research_sports_budget_200_daily.sql'));
 await pg.exec(read('supabase/migrations/20261017173910_sports_source_archive.sql'));
 await pg.exec(read('supabase/migrations/20261018151000_archive_dispatch_200_guard.sql'));
 // Synthetic attestation has the same bounded shape as verified Pro /status.
 await pg.query("insert into sefirot.chat_bridge_jobs(id,kind,request,status,completed_at,response) values('00000000-0000-0000-0000-000000000001','sports_probe',$1,'DONE',clock_timestamp(),$2)",[
   {queries:[{endpoint:'status',params:{}}]},
   {queries:[{rows:{plan:'Pro',requests_limit_day:7500}}]}
 ]);
 await pg.exec(read('supabase/migrations/20261019000000_expand_verified_api_football_pro_7500_daily.sql'));
 const {rows:[before]}=await pg.query('select count(*)::int attempts from sefirot_budget_private.sports_attempt');
 assert.equal(before.attempts,0);
 const {rows:[access]}=await pg.query("select has_function_privilege('service_role','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE') as service_arm, has_function_privilege('anon','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE') as anon_arm,has_function_privilege('service_role','public.sefirot_source_begin(uuid,integer,text,jsonb)','EXECUTE') as service_source");
 assert.equal(access.service_arm,false);assert.equal(access.anon_arm,false);
 assert.equal(access.service_source,false); // gateway grants independent
 for(const [n,m] of [[0,360],[7501,360],[7500,0],[7500,361]]) {
  await assert.rejects(pg.query('select sefirot_budget_private.arm_research_budget($1,$2)',[n,m]),/outside approved bounds/);
 }
 const {rows:[armed]}=await pg.query('select sefirot_budget_private.arm_research_budget(7500,360) a');
 assert.equal(armed.a.daily_call_cap,7500);
 assert.equal(armed.a.available_calls_cap,7500);
 assert.equal(armed.a.rate_limit_per_minute,60);
 assert.equal(armed.a.reserve_day,0);
 assert.equal(armed.a.money_authorized,false);
 const {rows:[budget]}=await pg.query('select reserve_day,remaining_day,minute_limit,enabled,valid_until,utc_day from sefirot_budget_private.sports_budget');
 assert.equal(budget.reserve_day,0);assert.equal(Number(budget.remaining_day),7500);
 assert.equal(budget.minute_limit,60);assert.equal(budget.enabled,true);
 const {rows:[first]}=await pg.query('select public.sefirot_sports_budget_reserve() a');
 assert.equal(first.a.allowed,true);
 const {rows:[finish]}=await pg.query("select public.sefirot_sports_budget_finish($1,'SUCCESS',7499,299,300) a",[first.a.permit]);
 assert.equal(finish.a.ok,true);
 const {rows:[denyMinute]}=await pg.query('select public.sefirot_sports_budget_reserve() a');
 assert.equal(denyMinute.a.allowed,false);
 assert.equal(denyMinute.a.reason,'MINUTE_LIMIT');
 await pg.query("insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts) values('00000000-0000-0000-0000-000000000002','sports_probe',$1,'RUNNING',1)",[{queries:[{endpoint:'fixtures',params:{league:39,season:2026}}]}]);
 const {rows:[dispatch]}=await pg.query("select public.sefirot_source_begin('00000000-0000-0000-0000-000000000002',1,'fixtures',$1) a",[{league:39,season:2026}]);
 assert.equal(dispatch.a.authorized,true);
 await assert.rejects(pg.query("select public.sefirot_source_begin('00000000-0000-0000-0000-000000000002',1,'fixtures',$1)",[{league:39,season:2026}]),/SOURCE_DISPATCH_ALREADY_ATTEMPTED/);
 // At exactly 7500 attempts in UTC day, no mutated row can allow another.
 await pg.exec("insert into sefirot_budget_private.sports_attempt(permit,started_at,finished_at,outcome) select gen_random_uuid(),clock_timestamp()-interval '20 seconds',clock_timestamp()-interval '19 seconds','SUCCESS' from generate_series(1,7499);");
 const {rows:[size]}=await pg.query('select count(*)::int n from sefirot_budget_private.sports_attempt');
 assert.equal(size.n,7500);
 await pg.exec("update sefirot_budget_private.sports_budget set minute_ready_at=clock_timestamp()-interval '1 minute', last_started_at=clock_timestamp()-interval '1 minute', remaining_day=5000 where singleton;");
 const {rows:[denied]}=await pg.query('select public.sefirot_sports_budget_reserve() a');
 assert.equal(denied.a.reason,'DAILY_LIMIT');assert.equal(denied.a.allowed,false);
 const {rows:[planner]}=await pg.query('select public.sefirot_plan_collection_day(39,2026) a');
 assert.equal(planner.a.reason,'DAILY_PRO_7500_ATTEMPT_CAP');
 await pg.exec("update sefirot_budget_private.sports_budget set enabled=false, valid_until=clock_timestamp()-interval '1 second' where singleton;");
 await assert.rejects(pg.query('select sefirot_budget_private.arm_research_budget(7500,360)'),/daily allowance exhausted/);
 const {rows:[still]}=await pg.query('select count(*)::int n from sefirot_budget_private.sports_attempt');
 assert.equal(still.n,7500);
 console.log(JSON.stringify({pro_quota_contract:'PASS',daily_limit:7500,rate_limit:60,attempts_not_reset:true,provider_calls:0}));
}finally{await pg.close();}
