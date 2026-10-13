"""Synthetic malformed SQLite schemas fail closed; input bytes stay original."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.cloud_sync import snapshot
from sefirot.contracts import canonical
from sefirot.repository import Repository
from sefirot.fixtures import example
from sefirot.service import Service


class ReleaseSchemaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'synthetic.sqlite'
        with closing(Repository(str(self.path))):
            pass

    def corrupt_audit_schema(self, populated=False):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('ALTER TABLE audit_logs RENAME TO old_audit_logs')
            db.execute('CREATE TABLE audit_logs(id INTEGER PRIMARY KEY,at TEXT,event TEXT,payload TEXT,previous_hash TEXT)')
            if populated:
                db.execute('INSERT INTO audit_logs(at,event,payload,previous_hash) VALUES(?,?,?,?)',
                           ('2030-01-01T00:00:00+00:00', 'TEST', '{}', '0'*64))
            db.commit()

    def assert_closed_unchanged(self):
        before = sha256(self.path.read_bytes()).hexdigest()
        with closing(Repository(str(self.path), read_only=True)) as repo:
            self.assertFalse(repo.verify())
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)

    def test_empty_malformed_audit_schema_is_not_integrity_true(self):
        self.corrupt_audit_schema()
        self.assert_closed_unchanged()

    def test_populated_malformed_audit_schema_returns_false_without_indexerror(self):
        self.corrupt_audit_schema(populated=True)
        self.assert_closed_unchanged()

    def test_primary_key_is_required_for_unique_record_binding(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('ALTER TABLE jobs RENAME TO old_jobs')
            db.execute('CREATE TABLE jobs(id TEXT,at TEXT,payload TEXT)')
            for variant in (1, 2):
                payload = {'id': 'synthetic-job', 'at': '2030-01-01T00:00:00+00:00', 'variant': variant}
                db.execute('INSERT INTO jobs VALUES(?,?,?)', (payload['id'], payload['at'], canonical(payload)))
            db.commit()
        self.assert_closed_unchanged()

    def test_cloud_snapshot_rejects_unkeyed_empty_table(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('ALTER TABLE jobs RENAME TO old_jobs')
            db.execute('CREATE TABLE jobs(id TEXT,at TEXT,payload TEXT)')
            db.commit()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'invalid SQLite ledger schema'):
            snapshot(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_cli_malformed_schema_exits_two_with_integrity_false(self):
        self.corrupt_audit_schema(populated=True)
        run = subprocess.run([sys.executable, str(ROOT/'sefirot.py'), '--db', str(self.path), 'verify'],
                             capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertFalse(json.loads(run.stdout)['integrity'])
        self.assertNotIn('Traceback', run.stderr)

    def test_healthy_empty_schema_remains_valid(self):
        before = self.path.read_bytes()
        with closing(Repository(str(self.path), read_only=True)) as repo:
            self.assertTrue(repo.verify())
        self.assertTrue(all(not rows for rows in snapshot(self.path).values()))
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_initial_version_read_closes_owned_connection(self):
        corrupt=self.path.parent/'corrupt.sqlite'
        corrupt.write_bytes(b'SQLite format 3\x00'+b'\x00'*4096)
        connection=sqlite3.connect(corrupt)
        with patch('sefirot.repository.sqlite3.connect',return_value=connection):
            with self.assertRaises(sqlite3.DatabaseError):
                Repository(str(corrupt),read_only=True)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_concurrent_valid_commit_cannot_mix_audit_and_record_snapshots(self):
        now=datetime(2030,1,1,12,tzinfo=timezone.utc)
        with closing(Repository(str(self.path))) as reader, closing(Repository(str(self.path))) as writer:
            reader.db.execute('PRAGMA journal_mode=WAL')
            case=example(now,'synthetic-snapshot-old')
            Service(reader,clock=lambda:now).capture(case['sports'],case['markets'])
            changed=[]
            def concurrent(statement):
                if statement=='SELECT * FROM teams' and not changed:
                    changed.append(True)
                    case=example(now,'synthetic-snapshot-new')
                    Service(writer,clock=lambda:now).capture(case['sports'],case['markets'])
            reader.db.set_trace_callback(concurrent)
            try:self.assertTrue(reader.verify())
            finally:reader.db.set_trace_callback(None)
            self.assertEqual(changed,[True])
            self.assertEqual(len(reader.all('predictions')),2)
            self.assertTrue(reader.verify())
            self.assertFalse(reader.db.in_transaction)

    def test_verification_preserves_existing_write_transaction(self):
        with closing(Repository(str(self.path))) as repo:
            with repo.transaction():
                repo.insert('teams','synthetic-outer',{'name':'synthetic-outer'})
                self.assertTrue(repo.verify())
                self.assertTrue(repo.db.in_transaction)
            self.assertEqual(repo.get('teams','synthetic-outer'),{'name':'synthetic-outer'})
