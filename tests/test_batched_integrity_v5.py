"""Fresh bytes, orphan coverage and bounded-query integrity verification."""
import copy
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import digest
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service


class BatchedIntegrityTests(unittest.TestCase):
    def seed(self, repo, n=1):
        now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        case = example(now, 'batch-integrity')
        original = Service(repo, clock=lambda: now).capture(case['sports'], case['markets'])
        for i in range(n - 1):
            row = copy.deepcopy(original)
            row['revision'] = i + 1
            row.pop('id')
            row['id'] = digest(row)
            repo.insert('predictions', row['id'], row, match_id=row['sports']['match']['id'],
                        model_id=row['model_id'], at=row['sealed_at'])
            repo.record_log('predictions', row['id'], row['sealed_at'], row)
        return original

    def test_query_count_is_independent_of_record_count(self):
        repo = Repository(':memory:')
        self.addCleanup(repo.close)
        self.seed(repo, 120)
        queries = []
        repo.db.set_trace_callback(queries.append)
        self.assertTrue(repo.verify())
        reads = [q for q in queries if q.upper().startswith('SELECT')]
        self.assertEqual(len(reads), 7)
        self.assertFalse(any('WHERE id=' in q for q in reads))

    def test_warm_cache_reads_external_updates_and_new_orphans(self):
        with tempfile.TemporaryDirectory() as directory, closing(
                Repository(Path(directory) / 'ledger.sqlite')) as repo:
            path = Path(directory) / 'ledger.sqlite'
            row = self.seed(repo)
            self.assertTrue(repo.verify())
            other = sqlite3.connect(path)
            try:
                other.execute('DROP TRIGGER predictions_no_update')
                other.execute("UPDATE predictions SET payload='{}' WHERE id=?", (row['id'],))
                other.commit()
                self.assertFalse(repo.verify())
                other.execute('UPDATE predictions SET payload=? WHERE id=?',
                              (json.dumps(row, sort_keys=True), row['id']))
                other.commit()
                self.assertTrue(repo.verify())
                repo.insert('predictions', 'unsigned', row, match_id=row['sports']['match']['id'],
                            model_id=row['model_id'], at=row['sealed_at'])
                self.assertFalse(repo.verify())
            finally:
                other.close()

    def test_all_references_checked_when_same_record_is_bound_twice(self):
        repo = Repository(':memory:')
        self.addCleanup(repo.close)
        row = self.seed(repo)
        repo.log('RECORD', row['sealed_at'], {'record_table': 'predictions',
                 'record_id': row['id'], 'record_hash': '0' * 64})
        self.assertFalse(repo.verify())

    def test_missing_or_invalid_record_reference_fails_closed(self):
        for table in ('predictions', 'audit_logs', 'predictions; DROP TABLE bets'):
            with self.subTest(table=table):
                repo = Repository(':memory:')
                try:
                    repo.log('RECORD', '2026-10-10T12:00:00Z',
                             {'record_table': table, 'record_id': 'missing', 'record_hash': '0' * 64})
                    self.assertFalse(repo.verify())
                finally:
                    repo.close()

    def test_unguarded_record_bindings_remain_checked(self):
        repo = Repository(':memory:')
        self.addCleanup(repo.close)
        row = {'status': 'DONE'}
        repo.insert('jobs', 'job', row, at='2026-10-10T12:00:00Z')
        repo.record_log('jobs', 'job', '2026-10-10T12:00:00Z', row)
        self.assertTrue(repo.verify())
        repo.db.execute('DROP TRIGGER jobs_no_update')
        repo.db.execute("UPDATE jobs SET payload='{}'")
        self.assertFalse(repo.verify())

    def test_readonly_verification_does_not_write_or_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.sqlite'
            repo = Repository(path)
            self.seed(repo)
            repo.close()
            before = path.read_bytes()
            readonly = Repository(path, read_only=True)
            try:
                self.assertTrue(readonly.verify())
                self.assertEqual(readonly.db.total_changes, 0)
            finally:
                readonly.close()
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
