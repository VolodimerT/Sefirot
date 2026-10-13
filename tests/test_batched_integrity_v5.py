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
from sefirot.repository import Repository, TABLES
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
        self.seed(repo)
        queries = []
        repo.db.set_trace_callback(queries.append)
        self.assertTrue(repo.verify())
        small_reads = [q for q in queries if q.upper().startswith('SELECT')]
        repo.db.set_trace_callback(None)
        self.seed(repo, 120)
        queries.clear()
        repo.db.set_trace_callback(queries.append)
        self.assertTrue(repo.verify())
        reads = [q for q in queries if q.upper().startswith('SELECT')]
        self.assertEqual(len(reads), len(small_reads))
        self.assertLessEqual(len(reads), len(TABLES) + 1)
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

    def test_warm_cache_rechecks_external_sql_timestamp_with_unchanged_payload(self):
        with tempfile.TemporaryDirectory() as directory, closing(
                Repository(Path(directory) / 'ledger.sqlite')) as repo:
            row = self.seed(repo)
            self.assertTrue(repo.verify())
            cached = dict(repo._record_digests)
            with closing(sqlite3.connect(Path(directory) / 'ledger.sqlite')) as other:
                other.execute('DROP TRIGGER predictions_no_update')
                other.execute("UPDATE predictions SET at='2000-01-01T00:00:00Z' WHERE id=?",
                              (row['id'],))
                other.commit()
                self.assertFalse(repo.verify())
                self.assertEqual(repo._record_digests, cached)
                other.execute('UPDATE predictions SET at=? WHERE id=?',
                              (row['sealed_at'], row['id']))
                other.commit()
                self.assertTrue(repo.verify())

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

    def test_validation_cache_is_bounded_and_uncached_tail_is_checked(self):
        repo=Repository(':memory:')
        self.addCleanup(repo.close)
        at='2026-10-10T12:00:00Z'
        for i in range(4100):
            identifier='cache-job-'+str(i)
            repo.insert('jobs',identifier,{'id':identifier,'at':at},at=at)
        self.assertTrue(repo.verify())
        self.assertLessEqual(len(repo._row_validations),4096)
        tail=next('cache-job-'+str(i) for i in range(4100)
                  if ('jobs','cache-job-'+str(i)) not in repo._row_validations)
        repo.db.execute('DROP TRIGGER jobs_no_update')
        repo.db.execute("UPDATE jobs SET at='2000-01-01T00:00:00Z' WHERE id=?",(tail,))
        self.assertFalse(repo.verify())
        self.assertLessEqual(len(repo._row_validations),4096)

    def test_validation_after_rollback_rechecks_reused_record_id(self):
        repo=Repository(':memory:')
        self.addCleanup(repo.close)
        at='2026-10-10T12:00:00Z'
        with self.assertRaisesRegex(ValueError,'rollback'):
            with repo.transaction():
                repo.insert('jobs','reused',{'id':'reused','at':at},at=at)
                self.assertTrue(repo.verify())
                raise ValueError('rollback')
        self.assertTrue(repo.verify())
        repo.insert('jobs','reused',{'id':'reused','at':at},at='2000-01-01T00:00:00Z')
        self.assertFalse(repo.verify())

    def test_warm_metadata_cache_does_not_hide_a_new_orphan(self):
        repo=Repository(':memory:')
        self.addCleanup(repo.close)
        row=self.seed(repo)
        self.assertTrue(repo.verify())
        row=copy.deepcopy(row);row.pop('id');row['revision']=1;row['id']=digest(row)
        repo.insert('predictions',row['id'],row,match_id=row['sports']['match']['id'],
                    model_id=row['model_id'],at=row['sealed_at'])
        self.assertFalse(repo.verify())

    def test_close_discards_both_bounded_caches(self):
        repo=Repository(':memory:')
        self.seed(repo);self.assertTrue(repo.verify())
        self.assertTrue(repo._row_validations);self.assertTrue(repo._record_digests)
        repo.close()
        self.assertFalse(repo._row_validations);self.assertFalse(repo._record_digests)

    def test_payload_column_case_does_not_put_payload_in_metadata_cache(self):
        repo=Repository(':memory:')
        self.addCleanup(repo.close)
        repo.db.execute('ALTER TABLE jobs RENAME COLUMN payload TO Payload')
        at='2026-10-10T12:00:00Z'
        note='SYNTHETIC_PRIVATE_NOTE_'+'x'*2000
        repo.insert('jobs','case-job',{'id':'case-job','at':at,'note':note},at=at)
        self.assertTrue(repo.verify());self.assertTrue(repo.verify())
        self.assertNotIn(note,repr(repo._row_validations))
        repo.db.execute('DROP TRIGGER jobs_no_update')
        repo.db.execute("UPDATE jobs SET at='2000-01-01T00:00:00Z'")
        self.assertFalse(repo.verify())

    def test_unguarded_record_bindings_remain_checked(self):
        repo = Repository(':memory:')
        self.addCleanup(repo.close)
        row = {'id': 'job', 'at': '2026-10-10T12:00:00Z', 'status': 'DONE'}
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
