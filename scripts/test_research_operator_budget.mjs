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
 console.log(JSON.stringify({operator_contract:'PASS',provider_calls:0,source:'SYNTHETIC_ONLY'}));
} finally {await pg.close();}
