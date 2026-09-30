"""Failure cases and round-trip checks for the optional private ledger mirror."""
from __future__ import annotations

import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cloud_sync import COLUMNS, CLOUD_COLUMNS, mirror, snapshot, sync
from sefirot.contracts import canonical, time
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service


class MemoryCursor:
    def __init__(self, cloud):
        self.cloud = cloud
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        if sql == 'SELECT current_user':
            self.rows = [(self.cloud.role,)]
        elif sql.startswith('SELECT pg_advisory_xact_lock'):
            self.rows = [(None,)]
        elif sql.startswith('SELECT ') and ' FROM sefirot.' in sql:
            projection, table = sql.removeprefix('SELECT ').split(' FROM sefirot.', 1)
            table = table.split(' ORDER BY id')[0]
            keys = projection.split(',')
            self.rows = [tuple(row[k] for k in keys)
                         for row in sorted(self.cloud.tables[table].values(), key=lambda r: r['id'])]
        elif sql.startswith('INSERT INTO sefirot.'):
            table = sql.split('(')[0].removeprefix('INSERT INTO sefirot.')
            columns = CLOUD_COLUMNS[table]
            self.cloud.calls += 1
            if self.cloud.fail_on == self.cloud.calls:
                raise RuntimeError('simulated disconnection')
            values = dict(zip(columns, params))
            values['payload'] = json.loads(values['payload'])
            if values['id'] in self.cloud.tables[table]:
                raise RuntimeError('primary key conflict')
            self.cloud.tables[table][values['id']] = values
        else:
            raise AssertionError(f'unexpected SQL: {sql}')

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class MemoryCloud:
    def __init__(self, role='sefirot_ingest'):
        self.role = role
        self.tables = {table: {} for table in COLUMNS}
        self.calls = 0
        self.fail_on = None

    def cursor(self):
        return MemoryCursor(self)

    def atomic_mirror(self, rows):
        before = copy.deepcopy(self.tables)
        try:
            return mirror(rows, self)
        except Exception:
            self.tables = before
            raise


class CloudSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'source with spaces.sqlite'
        repo = Repository(self.path)
        case = example()
        now = [time(case['sports']['as_of'])]
        service = Service(repo, clock=lambda: now[0])
        prediction = service.capture(case['sports'], case['markets'])
        now[0] = time(case['decision_at'])
        service.decide(prediction['id'], case['quotes'], case['recheck'],
                       {'bankroll': 1000, 'peak': 1000}, case['decision_at'])
        now[0] = time(case['result']['received_at'])
        service.result(case['result'])
        repo.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_full_round_trip_and_repeat_are_idempotent(self):
        rows = snapshot(self.path)
        cloud = MemoryCloud()
        first = cloud.atomic_mirror(rows)
        self.assertEqual(first['status'], 'MIRRORED')
        self.assertFalse(first['monetary_permission'])
        self.assertEqual(len(first['snapshot_hash']), 64)
        self.assertEqual(first['rows']['predictions'], 1)
        self.assertEqual(first['rows']['audit_logs'], len(rows['audit_logs']))
        self.assertEqual(cloud.atomic_mirror(rows), first)
        audit = cloud.tables['audit_logs'][1]
        self.assertEqual(audit['payload_source'], rows['audit_logs'][0]['payload'])
        self.assertEqual(audit['at_source'], rows['audit_logs'][0]['at'])
        self.assertEqual(audit['hash'], rows['audit_logs'][0]['hash'])

    def test_conflict_and_remote_extra_fail_closed(self):
        rows = snapshot(self.path)
        cloud = MemoryCloud()
        cloud.atomic_mirror(rows)
        cloud.tables['teams'][rows['teams'][0]['id']]['payload']['bogus'] = True
        before = copy.deepcopy(cloud.tables)
        with self.assertRaisesRegex(ValueError, 'cloud conflict'):
            cloud.atomic_mirror(rows)
        self.assertEqual(cloud.tables, before)
        cloud.tables['teams'][rows['teams'][0]['id']]['payload'].pop('bogus')
        cloud.tables['teams']['stray'] = {'id': 'stray', 'payload': {'extra': True}}
        with self.assertRaisesRegex(ValueError, 'cloud conflict'):
            cloud.atomic_mirror(rows)

    def test_unprivileged_role_and_partial_failure_cannot_commit(self):
        rows = snapshot(self.path)
        cloud = MemoryCloud('postgres')
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            cloud.atomic_mirror(rows)
        self.assertTrue(all(not batch for batch in cloud.tables.values()))
        cloud.role = 'sefirot_ingest'
        cloud.fail_on = 3
        with self.assertRaisesRegex(RuntimeError, 'disconnection'):
            cloud.atomic_mirror(rows)
        self.assertTrue(all(not batch for batch in cloud.tables.values()))

    def test_local_corruption_and_missing_credentials_rejected(self):
        self.assertTrue(snapshot(self.path)['audit_logs'])
        with self.assertRaisesRegex(ValueError, 'requires .*DSN'):
            sync(self.path, dsn='postgresql://example', ca='/no/cert')
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            snapshot(Path(self.temp.name) / 'missing.sqlite')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER audit_logs_no_update')
            db.execute("UPDATE audit_logs SET previous_hash=? WHERE id=1", ('a' * 64,))
        with self.assertRaisesRegex(ValueError, 'audit chain'):
            snapshot(self.path)

    def test_windows_style_entrypoint_local_check_without_cloud_secrets(self):
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'sefirot.py'),
                   '--db', str(self.path), 'sync-supabase', '--check-local']
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result['status'], 'LOCAL_VERIFIED')
        self.assertEqual(result['rows']['predictions'], 1)
        self.assertFalse(result['cloud_written'])
        self.assertEqual(len(result['snapshot_hash']), 64)

    def test_snapshot_limit_refuses_unbounded_memory(self):
        with patch('sefirot.cloud_sync.MAX_ROWS', 1):
            with self.assertRaisesRegex(ValueError, 'bounded sync limit'):
                snapshot(self.path)

    def test_transport_forces_verified_tls_and_atomic_commit(self):
        cloud = MemoryCloud()
        ca = Path(self.temp.name) / 'ca.crt'
        ca.write_text('test only', encoding='utf-8')
        arguments = {}

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def transaction(self):
                return self

            def execute(self, statement):
                self_statement = 'SET TRANSACTION ISOLATION LEVEL SERIALIZABLE'
                assert statement == self_statement

            def cursor(self):
                return cloud.cursor()

        def connect(dsn, **kwargs):
            arguments.update(dsn=dsn, **kwargs)
            return Connection()

        fake_driver = types.SimpleNamespace(connect=connect, Error=RuntimeError)
        with patch.dict(sys.modules, {'psycopg': fake_driver}):
            result = sync(self.path, dsn='postgresql://example', ca=str(ca))
        self.assertEqual(result['status'], 'MIRRORED')
        self.assertEqual(arguments['sslmode'], 'verify-full')
        self.assertEqual(arguments['sslrootcert'], str(ca))
        self.assertEqual(arguments['connect_timeout'], 10)

    def test_noncanonical_payload_rejected_before_network(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER teams_no_update')
            db.execute('UPDATE teams SET payload=? WHERE id=(SELECT id FROM teams LIMIT 1)',
                       (json.dumps({'z': 1, 'a': 2}),))
        with self.assertRaisesRegex(ValueError, 'invalid teams'):
            snapshot(self.path)


if __name__ == '__main__':
    unittest.main()
