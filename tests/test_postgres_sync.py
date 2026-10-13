"""Real PostgreSQL checks, opt-in only for the isolated local CI database."""
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import tempfile
import unittest
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.cloud_sync import COLUMNS, mirror, snapshot
from sefirot.contracts import time
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service


def local_test_dsn(value):
    parsed = urlparse(value)
    if (parsed.scheme not in ('postgres', 'postgresql') or
            parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or
            parsed.path != '/sefirot_sync_test' or parsed.query or parsed.fragment):
        raise ValueError('isolated local sefirot_sync_test database required')
    return value


class PostgresTargetTests(unittest.TestCase):
    def test_remote_or_overridden_test_targets_are_rejected(self):
        for dsn in ('postgresql://remote.example/sefirot_sync_test',
                    'postgresql://localhost/postgres',
                    'postgresql://localhost/sefirot_sync_test?host=remote.example',
                    'postgresql://localhost/sefirot_sync_test#override'):
            with self.subTest(dsn=dsn), self.assertRaises(ValueError):
                local_test_dsn(dsn)


@unittest.skipUnless(os.environ.get('SEFIROT_TEST_POSTGRES_DSN'), 'isolated PostgreSQL CI only')
class PostgresMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Validate the target before opening any database connection.
        dsn = local_test_dsn(os.environ['SEFIROT_TEST_POSTGRES_DSN'])
        import psycopg
        cls.driver = psycopg
        cls.admin = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        cls.addClassCleanup(cls.admin.close)
        # A fresh service container must have no existing ledger or app roles.
        if cls.admin.execute("SELECT to_regnamespace('sefirot')").fetchone()[0] is not None:
            raise ValueError('fresh isolated test database required')
        for role in ('anon', 'authenticated', 'service_role'):
            cls.admin.execute(f'CREATE ROLE {role} NOLOGIN')
        cls.admin.execute((ROOT / 'schema/supabase_core.sql').read_text(encoding='utf-8'))
        cls.admin.execute((ROOT / 'schema/supabase_ingest_role.sql').read_text(encoding='utf-8'))

    def setUp(self):
        # Only the guarded, fresh local service database is reachable here.
        tables = ','.join('sefirot.' + table for table in COLUMNS)
        self.admin.execute(f'TRUNCATE {tables} CASCADE')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.sqlite'
            repo = Repository(path)
            try:
                case = example(datetime(2026, 10, 13, 10, tzinfo=timezone.utc))
                clock = [time(case['sports']['as_of'])]
                service = Service(repo, clock=lambda: clock[0])
                prediction = service.capture(case['sports'], case['markets'])
                clock[0] = time(case['decision_at'])
                service.decide(prediction['id'], case['quotes'], case['recheck'],
                    {'bankroll': 1000, 'peak': 1000}, case['decision_at'])
                clock[0] = time(case['result']['received_at'])
                service.result(case['result'])
                self.rows = snapshot(path)
            finally:
                repo.close()

    def upload(self, rows=None):
        with self.admin.transaction():
            self.admin.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
            self.admin.execute('SET LOCAL ROLE sefirot_ingest')
            return mirror(self.rows if rows is None else rows, self.admin)

    def test_real_round_trip_is_idempotent_and_preserves_audit_bytes(self):
        first = self.upload()
        self.assertEqual(self.upload(), first)
        self.assertEqual(first['status'], 'MIRRORED')
        self.assertFalse(first['monetary_permission'])
        row = self.admin.execute('SELECT at_source,payload_source,hash FROM sefirot.audit_logs WHERE id=1').fetchone()
        source = self.rows['audit_logs'][0]
        self.assertEqual(row, (source['at'], source['payload'], source['hash']))

    def test_insert_failure_rolls_back_all_preceding_tables(self):
        self.admin.execute("""
            CREATE FUNCTION sefirot.test_reject_result() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'isolated test failure'; END $$;
            CREATE TRIGGER test_reject_result BEFORE INSERT ON sefirot.results
            FOR EACH ROW EXECUTE FUNCTION sefirot.test_reject_result();
        """)
        try:
            with self.assertRaises(self.driver.Error):
                self.upload()
            for table in COLUMNS:
                with self.subTest(table=table):
                    self.assertEqual(self.admin.execute(f'SELECT COUNT(*) FROM sefirot.{table}').fetchone()[0], 0)
        finally:
            self.admin.execute('DROP TRIGGER test_reject_result ON sefirot.results')
            self.admin.execute('DROP FUNCTION sefirot.test_reject_result()')
        self.assertEqual(self.upload()['status'], 'MIRRORED')

    def test_wrong_role_and_extra_cloud_record_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'dedicated sefirot_ingest'):
            mirror(self.rows, self.admin)
        self.admin.execute("INSERT INTO sefirot.teams(id,payload) VALUES ('stray','{}')")
        with self.assertRaisesRegex(ValueError, 'cloud conflict'):
            self.upload()
        self.assertEqual(self.admin.execute('SELECT COUNT(*) FROM sefirot.predictions').fetchone()[0], 0)

    def test_client_roles_cannot_read_and_ingest_cannot_mutate(self):
        self.upload()
        for role in ('anon', 'authenticated', 'service_role'):
            with self.subTest(role=role), self.assertRaises(self.driver.errors.InsufficientPrivilege):
                with self.admin.transaction():
                    self.admin.execute(f'SET LOCAL ROLE {role}')
                    self.admin.execute('SELECT * FROM sefirot.predictions')
        for operation in ('UPDATE sefirot.teams SET payload=payload', 'DELETE FROM sefirot.teams'):
            with self.subTest(operation=operation), self.assertRaises(self.driver.errors.InsufficientPrivilege):
                with self.admin.transaction():
                    self.admin.execute('SET LOCAL ROLE sefirot_ingest')
                    self.admin.execute(operation)


if __name__ == '__main__':
    unittest.main()
