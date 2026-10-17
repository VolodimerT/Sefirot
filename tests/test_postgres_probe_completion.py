"""Native PostgreSQL proof against a fresh, explicitly isolated local target."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
import unittest

ROOT=Path(__file__).resolve().parents[1]

def local_probe_dsn(value):
    parsed=urlsplit(value)
    if (parsed.scheme not in ('postgres','postgresql')
            or parsed.hostname not in ('127.0.0.1','localhost','::1')
            or parsed.path!='/sefirot_probe_test' or parsed.query or parsed.fragment):
        raise ValueError('fresh isolated local sefirot_probe_test required')
    return value

class ProbePostgresTargetTests(unittest.TestCase):
    def test_remote_overridden_and_other_local_databases_are_rejected(self):
        for value in ('postgresql://remote.invalid/sefirot_probe_test','postgresql://localhost/postgres',
                      'postgresql://localhost/sefirot_probe_test?host=remote.invalid',
                      'postgresql://localhost/sefirot_probe_test#override'):
            with self.subTest(value=value),self.assertRaises(ValueError):local_probe_dsn(value)

@unittest.skipUnless(os.environ.get('SEFIROT_TEST_PROBE_POSTGRES_DSN'),'isolated native probe PostgreSQL CI only')
class NativeProbePostgresTests(unittest.TestCase):
    @contextmanager
    def isolated(self):
        # Each method rolls back its own schemas, roles, rows and function DDL.
        dsn=local_probe_dsn(os.environ['SEFIROT_TEST_PROBE_POSTGRES_DSN'])
        import psycopg
        with psycopg.connect(dsn,autocommit=True,connect_timeout=10) as admin:
            self.assertIsNone(admin.execute("select to_regnamespace('sefirot')").fetchone()[0],
                              'fresh isolated database required')
            admin.execute('begin')
            try:yield admin
            finally:admin.execute('rollback')

    def sql(self,filename):
        sql=(ROOT/filename).read_text(encoding='utf-8')
        # The test owns the outer transaction; keep migration DDL in savepoints.
        return re.sub(r'^commit;\s*$', '', re.sub(r'^begin;\s*$', '', sql, count=1, flags=re.M),count=1,flags=re.M)

    def fn_state(self,admin):
        return admin.execute("select p.proname,p.prosrc,p.proacl::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','sefirot') and p.proname in ('sefirot_chat_complete','sefirot_chat_claim','sefirot_probe_complete','chat_complete_before_probe_fence') order by p.proname").fetchall()

    def test_populated_situation_baseline_guards_and_park(self):
        from test_situation_populated_upgrade import run_native_situation_upgrade
        with self.isolated() as admin:
            run_native_situation_upgrade(self,admin)

    def test_resume_existing_queue_keeps_budget_and_leased_completion(self):
        with self.isolated() as admin:
            for name in ('tests/fixtures/chat_bridge_legacy.sql',
                         'tests/fixtures/probe_rollout_legacy.sql',
                         'supabase/migrations/20261015161027_probe_completion_fence.sql',
                         'supabase/review_only/20261015161311_park_probe_queue.sql'):
                admin.execute(self.sql(name))
            before = admin.execute('select * from sefirot_budget_private.sports_budget').fetchall()
            functions = [(name, body) for name, body, acl in self.fn_state(admin)]
            resume = self.sql('supabase/migrations/20261017114454_resume_probe_worker.sql')
            admin.execute(resume); admin.execute(resume)
            self.assertEqual(before, admin.execute('select * from sefirot_budget_private.sports_budget').fetchall())
            self.assertEqual(functions, [(name, body) for name, body, acl in self.fn_state(admin)])
            admin.execute("insert into sefirot.chat_bridge_jobs(id,kind,request) values('00000000-0000-0000-0000-000000000093','sports_probe','{\"queries\":[{\"endpoint\":\"status\",\"params\":{}}]}')")
            admin.execute('set local role service_role')
            job = admin.execute('select public.sefirot_chat_claim()').fetchone()[0]['job']
            self.assertEqual(job['attempt'], 1)
            args=(job['id'], 1, False, None, 'RESEARCH_RUNNER_ERROR')
            query='select public.sefirot_probe_complete(%s,%s,%s,%s,%s)'
            ack=admin.execute(query,args).fetchone()[0]
            self.assertEqual(admin.execute(query,args).fetchone()[0], ack)
            self.assertTrue(ack['completed'])
            self.assertIsNone(admin.execute('select public.sefirot_chat_claim()').fetchone()[0]['job'])
            admin.execute('reset role')

    def test_same_cases_native_sql_permissions_idempotency_and_fencing(self):
        with self.isolated() as admin:
            for filename in ('tests/fixtures/chat_bridge_legacy.sql',
                             'schema/supabase_chat_situation.sql','tests/fixtures/probe_completion_cases.sql'):
                admin.execute(self.sql(filename))
            self.assertEqual(admin.execute('select count(*) from public.probe_test_cases').fetchone()[0],10)

    def test_populated_upgrade_drift_guards_and_safe_park_keep_originals(self):
        import psycopg
        manifest=json.loads((ROOT/'schema/probe_rollout_manifest.json').read_text())
        up=self.sql(manifest['up']);park=self.sql(manifest['park'])
        cases=json.loads((ROOT/'tests/fixtures/probe_rollout_rejections.json').read_text())
        with self.isolated() as admin:
            admin.execute(self.sql('tests/fixtures/chat_bridge_legacy.sql'))
            admin.execute(self.sql('tests/fixtures/probe_rollout_legacy.sql'))
            def rejected(case):
                with self.subTest(fault=case['name']):
                    admin.execute('savepoint fault')
                    try:
                        admin.execute(case['mutate']);before=self.fn_state(admin)
                        admin.execute('savepoint apply')
                        with self.assertRaisesRegex(psycopg.Error,case['error']):admin.execute(up)
                        admin.execute('rollback to savepoint apply')
                        self.assertEqual(self.fn_state(admin),before)
                    finally:admin.execute('rollback to savepoint fault;release savepoint fault')
            for case in cases:
                if not case.get('after_upgrade'):rejected(case)
            before=self.fn_state(admin)
            admin.execute('savepoint interrupted')
            with self.assertRaisesRegex(psycopg.Error,'SYNTHETIC_INTERRUPTED'):
                admin.execute(up+"\ndo $$ begin raise exception 'SYNTHETIC_INTERRUPTED';end $$;")
            admin.execute('rollback to savepoint interrupted;release savepoint interrupted')
            self.assertEqual(self.fn_state(admin),before)
            admin.execute(up);after=self.fn_state(admin)
            original_body=next(row[1] for row in before if row[0]=='sefirot_chat_complete')
            self.assertEqual(next(row[1] for row in after if row[0]=='chat_complete_before_probe_fence'),original_body)
            probe_body=next(row[1] for row in after if row[0]=='sefirot_probe_complete')
            self.assertEqual(hashlib.sha256(probe_body.encode()).hexdigest(),manifest['probe_body_sha256'])
            admin.execute(up);self.assertEqual(self.fn_state(admin),after)
            for case in cases:
                if not case.get('before_upgrade_only'):rejected(case)
            admin.execute(self.sql('tests/fixtures/probe_rollout_assertions.sql'))
            admin.execute(self.sql('tests/fixtures/probe_completion_cases.sql'))
            self.assertEqual(admin.execute('select count(*) from public.probe_test_cases').fetchone()[0],10)
            admin.execute(park);admin.execute(park)
            self.assertEqual(admin.execute("select has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE'),has_function_privilege('service_role','public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','EXECUTE')").fetchone(),(False,False))
            admin.execute('select public.assert_probe_rollout_originals()')
            admin.execute(up)
            self.assertFalse(admin.execute("select has_function_privilege('service_role','public.sefirot_chat_claim()','EXECUTE')").fetchone()[0])

if __name__=='__main__':unittest.main()
