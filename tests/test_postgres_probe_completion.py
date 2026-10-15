"""Native PostgreSQL proof against a fresh, explicitly isolated local target."""
import os
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
    def test_same_cases_native_sql_permissions_idempotency_and_fencing(self):
        dsn=local_probe_dsn(os.environ['SEFIROT_TEST_PROBE_POSTGRES_DSN'])
        import psycopg
        with psycopg.connect(dsn,autocommit=True,connect_timeout=10) as admin:
            self.assertIsNone(admin.execute("select to_regnamespace('sefirot')").fetchone()[0],
                              'fresh isolated database required')
            for filename in ('tests/fixtures/chat_bridge_legacy.sql',
                             'schema/supabase_chat_situation.sql','tests/fixtures/probe_completion_cases.sql'):
                admin.execute((ROOT/filename).read_text(encoding='utf-8'))
            self.assertEqual(admin.execute('select count(*) from public.probe_test_cases').fetchone()[0],10)

if __name__=='__main__':unittest.main()
