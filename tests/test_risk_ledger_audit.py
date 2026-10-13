"""Real SQLite Repository/Service lifecycle; synthetic data, never a wager."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from sefirot import Repository, Service
from sefirot.contracts import time
from sefirot.fixtures import example
from risk_ledger_audit import audit


class OriginalLedgerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'original.sqlite'
        self.repo = Repository(self.path)
        self.now = datetime(2026, 9, 26, 18, tzinfo=timezone.utc)
        self.svc = Service(self.repo, clock=lambda: self.now)
        self.case = example(self.now)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def lifecycle(self, result=True):
        p = self.svc.capture(self.case['sports'], self.case['markets'])
        self.now = time(self.case['decision_at'])
        d = self.svc.decide(p['id'], self.case['quotes'], self.case['recheck'],
                            {'bankroll': 1000., 'peak': 1000.}, self.case['decision_at'])
        self.svc.execution(d['id'], {'id': 'private-execution-id', 'market': d['candidates'][0]['key'],
                           'odds': 2.1, 'stake': 5., 'bookmaker': 'SYNTHETIC_BOOK',
                           'origin': 'EXTERNAL'}, self.case['decision_at'])
        if result:
            self.now = time(self.case['result']['received_at'])
            self.svc.result(self.case['result'])
        return p, d

    def test_missing_database_is_not_created(self):
        with self.assertRaises(Exception):
            audit(self.path.with_name('missing.sqlite'), self.now.isoformat())
        self.assertFalse(self.path.with_name('missing.sqlite').exists())

    def test_empty_is_not_proof_of_settlement(self):
        out = audit(self.path, self.now.isoformat())
        self.assertEqual(out['status'], 'INSUFFICIENT_SETTLEMENT_RECORDS')
        self.assertEqual(out['settled_exposures_checked'], 0)

    def test_actual_repository_and_service_settlement(self):
        self.lifecycle()
        out = audit(self.path, self.now.isoformat())
        self.assertEqual(out['status'], 'INTERNAL_CHRONOLOGY_CHECKED')
        self.assertEqual(out['service_contexts_checked'], 1)
        self.assertEqual(out['settled_exposures_checked'], 1)
        self.assertEqual(out['defects'], {})
        self.assertEqual(out['synthetic_predictions'], 1)
        self.assertFalse(out['monetary_permission'])

    def test_late_result_not_visible_at_placement(self):
        self.lifecycle()
        out = audit(self.path, self.case['decision_at'])
        self.assertEqual(out['status'], 'INSUFFICIENT_SETTLEMENT_RECORDS')
        self.assertEqual(out['settled_exposures_checked'], 0)
        self.assertEqual(out['defects'], {})

    def test_open_exposure_remains_open(self):
        self.lifecycle(result=False)
        out = audit(self.path, self.now.isoformat())
        self.assertEqual(out['status'], 'INSUFFICIENT_SETTLEMENT_RECORDS')
        self.assertEqual(out['defects'], {})

    def test_bound_impossible_result_rejected_without_service_write(self):
        self.lifecycle(result=False)
        r = dict(self.case['result'], finished_at=self.case['decision_at'])
        self.repo.insert('results', r['match_id'], r, at=r['received_at'])
        self.repo.record_log('results', r['match_id'], r['received_at'], r)
        self.now = time(r['received_at'])
        self.assertTrue(self.repo.verify())
        out = audit(self.path, self.now.isoformat())
        self.assertEqual(out['status'], 'CHRONOLOGY_INVALID')
        self.assertEqual(out['defects']['RESULT_CHRONOLOGY'], 1)

    def test_negative_stake_bound_to_chain_rejected(self):
        _, d = self.lifecycle(result=False)
        b = self.repo.get('bets', 'private-execution-id')
        bad = dict(b, id='bad-stake', stake=-1.)
        self.repo.insert('bets', bad['id'], bad, decision_id=d['id'], at=bad['at'])
        self.repo.record_log('bets', bad['id'], bad['at'], bad)
        self.assertTrue(self.repo.verify())
        self.assertEqual(audit(self.path, self.now.isoformat())['status'], 'RECORD_SHAPE_REJECTED')

    def test_future_prediction_does_not_get_as_of_context(self):
        self.lifecycle()
        out = audit(self.path, '2026-09-26T17:59:59+00:00')
        self.assertEqual(out['service_contexts_checked'], 0)
        self.assertEqual(out['settled_exposures_checked'], 0)

    def test_bytes_and_original_rows_unchanged(self):
        self.lifecycle()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        first = audit(self.path, self.now.isoformat())
        second = audit(self.path, self.now.isoformat())
        self.assertEqual(first, second)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_sql_column_binding_is_checked_even_if_payload_hash_valid(self):
        self.lifecycle()
        self.repo.db.execute('DROP TRIGGER bets_no_update')
        self.repo.db.execute("UPDATE bets SET at='2026-09-26T17:00:00+00:00'")
        self.assertFalse(self.repo.verify())
        out = audit(self.path, self.now.isoformat())
        self.assertEqual(out['status'], 'JOURNAL_INVALID')
        self.assertEqual(out['service_contexts_checked'], 0)

    def test_audit_chain_corruption_blocks_context(self):
        self.lifecycle()
        self.repo.db.execute('DROP TRIGGER audit_logs_no_update')
        self.repo.db.execute("UPDATE audit_logs SET hash='corrupted' WHERE id=1")
        out = audit(self.path, self.now.isoformat())
        self.assertEqual(out['status'], 'JOURNAL_INVALID')
        self.assertEqual(out['service_contexts_checked'], 0)

    def test_output_contains_no_private_record_ids_or_sources(self):
        self.lifecycle()
        out = str(audit(self.path, self.now.isoformat()))
        self.assertNotIn('private-execution-id', out)
        self.assertNotIn('SYNTHETIC_BOOK', out)


if __name__ == '__main__':
    unittest.main()
