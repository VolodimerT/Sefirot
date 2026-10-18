/* Same actual SQL cases used by native PostgreSQL CI. Never contacts a provider. */
import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs';
const sql=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const pg=new PGlite();
try {
 await pg.exec('create role anon; create role authenticated;create role service_role bypassrls;');
 await pg.exec(sql('server/migrations/20261012_shared_sports_budget.sql'));
 await pg.exec(sql('supabase/migrations/20261015_research_api_budget_operator.sql'));
 await pg.exec(sql('tests/fixtures/research_operator_budget_cases.sql'));
 // The old 5/day contract remains regression-tested above. Reset only this disposable
 // synthetic state, then test the production 200/day migration separately.
 await pg.exec("update sefirot_budget_private.sports_budget set enabled=false,in_flight=null,reserved_at=null,last_started_at=null,minute_ready_at=clock_timestamp()-interval '2 minutes' where singleton;");
 await pg.exec(sql('supabase/migrations/20261018172000_expand_research_sports_budget_200_daily.sql'));
 await pg.exec(sql('tests/fixtures/research_operator_budget_200_cases.sql'));
 console.log(JSON.stringify({operator_contract:'PASS',provider_calls:0,source:'SYNTHETIC_ONLY'}));
} finally {await pg.close();}
