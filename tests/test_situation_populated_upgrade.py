"""Owned populated-upgrade proof; no production SQL or real provider calls.

The same guard cases and SQL witnesses run in PGlite and in the existing native
PostgreSQL probe CI job. Synthetic lease tests explicitly grant LOCAL access;
the deployable migration always keeps the queue and completions parked.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/test_situation_upgrade.mjs'
MANIFEST=ROOT/'schema/situation_rollout_manifest.json'


def shared_cases():
    source=SCRIPT.read_text(encoding='utf-8')
    cases=json.loads(re.search(r'export const rejectionCases = ([\s\S]*?);\n// END_REJECTION_CASES',source)[1])
    sql={name:body for name,body in re.findall(r'const (\w+SQL) = `([\s\S]*?)`;',source)}
    request=json.loads(re.search(r'^const request = (.*);$',source,re.M)[1])
    response=json.loads(re.search(r'^const response = (.*);$',source,re.M)[1])
    return cases,sql,request,response


class SituationPopulatedUpgradeTests(unittest.TestCase):
    def test_delta_reuses_exact_canonical_bodies_and_never_replaces_fences(self):
        manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
        delta=(ROOT/manifest['up']).read_text(encoding='utf-8')
        canonical=(ROOT/'schema/supabase_chat_situation.sql').read_text(encoding='utf-8')
        definitions=canonical[canonical.index('create table sefirot.chat_situation_receipts'):
                              canonical.index('-- Private machine-queue completion')].strip()
        self.assertIn(definitions,delta)
        self.assertNotRegex(delta,r'(?i)create\s+(?:or\s+replace\s+)?function\s+(?:public\.sefirot_(?:chat|probe)|sefirot\.chat_complete_before)')
        self.assertEqual(manifest['extended_queue_kinds'],manifest['existing_queue_kinds']+['situation'])
        self.assertFalse(manifest['queue_resume']);self.assertFalse(manifest['provider_calls'])
        self.assertEqual(manifest['mode'],'PARKED_RESEARCH_ONLY');self.assertFalse(manifest['money'])
        for function in manifest['functions']:
            name=function['signature'].split('(')[0]
            body=re.search(r'create function '+re.escape(name)+r'\([\s\S]*?as \$\$([\s\S]*?)\$\$;',canonical)[1]
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),function['body_sha256'])
        cases,sql,_,_=shared_cases()
        self.assertEqual(len(cases),58);self.assertIn('catalogStateSQL',sql)

    def test_actual_populated_postgres_upgrade_guards_leases_and_park(self):
        node=shutil.which('node');self.assertIsNotNone(node,'Node required; never skip SQL proof')
        run=subprocess.run([node,str(SCRIPT)],cwd=ROOT,capture_output=True,text=True,
                           encoding='utf-8',timeout=60)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout),{'situation_upgrade_groups':107,
                                               'provider_calls':0,'synthetic_only':True})


def run_native_situation_upgrade(test,admin):
    """Called by existing isolated native probe CI; no Node/npm dependency."""
    import psycopg
    from psycopg.types.json import Jsonb
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    cases,sql,request,response=shared_cases()
    for filename in ('tests/fixtures/chat_bridge_legacy.sql','tests/fixtures/probe_rollout_legacy.sql',
                     manifest['required_probe_up'],manifest['required_probe_park']):
        admin.execute(test.sql(filename))
    up=test.sql(manifest['up'])
    admin.execute(sql['populatedWitnessSQL'])
    admin.execute('savepoint without_ingest');admin.execute(up)
    admin.execute('rollback to savepoint without_ingest;release savepoint without_ingest')
    admin.execute(sql['documentedIngestSQL'])
    state=lambda name:admin.execute(sql[name]).fetchone()[0]
    original=state('originalStateSQL')
    admin.execute('savepoint unsafe_previous_path')
    with test.assertRaisesRegex(psycopg.Error,'chat_bridge_jobs_kind_check'):
        admin.execute(test.sql('schema/supabase_chat_situation.sql'))
    admin.execute('rollback to savepoint unsafe_previous_path;release savepoint unsafe_previous_path')
    test.assertEqual(state('originalStateSQL'),original)

    def rejected(case):
        with test.subTest(situation_fault=case['name']):
            admin.execute('savepoint fault')
            try:
                admin.execute(case['mutate'])
                before=state('originalStateSQL');catalog=state('catalogStateSQL')
                admin.execute('savepoint application')
                with test.assertRaisesRegex(psycopg.Error,case['error']):admin.execute(up)
                admin.execute('rollback to savepoint application;release savepoint application')
                test.assertEqual(state('originalStateSQL'),before)
                test.assertEqual(state('catalogStateSQL'),catalog)
            finally:admin.execute('rollback to savepoint fault;release savepoint fault')

    for case in cases:
        if case['stage']!='after':rejected(case)
    admin.execute('savepoint interrupted')
    with test.assertRaisesRegex(psycopg.Error,'SYNTHETIC_INTERRUPTION'):
        admin.execute(up+"\ndo $$begin raise exception 'SYNTHETIC_INTERRUPTION';end$$;")
    admin.execute('rollback to savepoint interrupted;release savepoint interrupted')
    test.assertEqual(state('originalStateSQL'),original)
    test.assertIsNone(admin.execute("select to_regclass('sefirot.chat_situation_receipts')").fetchone()[0])
    admin.execute(up);test.assertEqual(state('originalStateSQL'),original)
    admin.execute(sql['parkedAssertionsSQL']);baseline=state('baselineStateSQL')
    admin.execute(up);test.assertEqual(state('originalStateSQL'),original)
    test.assertEqual(state('baselineStateSQL'),baseline)
    for case in cases:
        if case['stage']!='before':rejected(case)
    for function in manifest['functions']:
        body=admin.execute('select prosrc from pg_proc where oid=to_regprocedure(%s)',
                           (function['signature'],)).fetchone()[0]
        test.assertEqual(hashlib.sha256(body.encode()).hexdigest(),function['body_sha256'])
    envelope={'body':{'origin':'SYNTHETIC_TEST_ONLY','original_json':'{"provider":"owned"}'},
              'collector_signature':'synthetic'}
    admin.execute('insert into sefirot.chat_situation_receipts(receipt_id,envelope) values(%s,%s)',
                  ('a'*64,Jsonb(envelope)))
    admin.execute('set role service_role')
    test.assertEqual(admin.execute('select public.sefirot_situation_source(%s)',('a'*64,)).fetchone()[0],
                     {'receipt':envelope})
    admin.execute('reset role')

    def denied(query,params=None,pattern='permission denied'):
        admin.execute('savepoint denial');admin.execute('set role service_role')
        with test.assertRaisesRegex(psycopg.Error,pattern):admin.execute(query,params)
        admin.execute('rollback to savepoint denial;release savepoint denial')

    for query in ('select public.sefirot_chat_claim()',
                  "select public.sefirot_probe_complete(null,1,false,null,'RESEARCH_RUNNER_ERROR')",
                  'select public.sefirot_situation_enqueue(null)',
                  'select public.sefirot_situation_complete(null,1,false,null,null)',
                  'select * from sefirot.chat_situation_receipts'):
        denied(query)
    for query in ("update sefirot.chat_situation_receipts set envelope='{}'",
                  'delete from sefirot.chat_situation_receipts'):
        admin.execute('savepoint immutable')
        with test.assertRaisesRegex(psycopg.Error,'APPEND_ONLY'):admin.execute(query)
        admin.execute('rollback to savepoint immutable;release savepoint immutable')
    # Explicit grants exist only inside this disposable rolled-back test.
    signatures=('public.sefirot_chat_claim(),public.sefirot_situation_enqueue(jsonb),'
                'public.sefirot_situation_complete(uuid,integer,boolean,jsonb,text)')
    admin.execute('grant execute on function '+signatures+' to service_role')
    admin.execute('set role service_role')
    first=admin.execute('select public.sefirot_situation_enqueue(%s)',(Jsonb(request),)).fetchone()[0]
    test.assertTrue(admin.execute('select public.sefirot_situation_enqueue(%s)',
                                  (Jsonb(request),)).fetchone()[0]['reused'])
    job=admin.execute('select public.sefirot_chat_claim()').fetchone()[0]['job']
    test.assertEqual(job['id'],first['job_id']);test.assertEqual(job['attempt'],1)
    admin.execute('reset role')
    complete='select public.sefirot_situation_complete(%s,%s,%s,%s,%s)'
    denied(complete,(job['id'],2,True,Jsonb(response),None),'STALE_SITUATION_LEASE')
    denied('select public.sefirot_chat_complete(%s,true,%s,null)',
           (job['id'],Jsonb({})),'SITUATION_LEASE_REQUIRED')
    admin.execute("update sefirot.chat_bridge_jobs set claimed_at=now()-interval '4 minutes' where id=%s",
                  (job['id'],))
    admin.execute('set role service_role')
    job=admin.execute('select public.sefirot_chat_claim()').fetchone()[0]['job']
    test.assertEqual(job['attempt'],2)
    args=(job['id'],2,True,Jsonb(response),None)
    test.assertTrue(admin.execute(complete,args).fetchone()[0]['completed'])
    test.assertTrue(admin.execute(complete,args).fetchone()[0]['completed'])
    admin.execute('reset role')
    denied(complete,(job['id'],2,True,Jsonb({**response,'execution_enabled':True}),None),
           'INVALID_SITUATION_RESPONSE')
    admin.execute('revoke execute on function '+signatures+' from service_role')
    final_original=state('originalStateSQL');final_baseline=state('baselineStateSQL')
    admin.execute(up);test.assertEqual(state('originalStateSQL'),final_original)
    test.assertEqual(state('baselineStateSQL'),final_baseline);admin.execute(sql['parkedAssertionsSQL'])


if __name__=='__main__':unittest.main()
