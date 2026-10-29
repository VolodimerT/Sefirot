"""Regression cases reproduced in the read-only audit of main."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.cloud_sync import snapshot
from sefirot.backtesting import walk_forward
from sefirot.contracts import time
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.worker import process_inbox

NOW = datetime(2026, 10, 13, 10, tzinfo=timezone.utc)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.sqlite'
        self.repo = Repository(self.path)
        self.addCleanup(self.repo.close)
        self.clock = [NOW]
        self.service = Service(self.repo, clock=lambda: self.clock[0])
        self.case = example(NOW)

    def capture(self):
        return self.service.capture(self.case['sports'], self.case['markets'])

    def decision(self, prediction):
        self.clock[0] = time(self.case['decision_at'])
        return self.service.decide(prediction['id'], self.case['quotes'], self.case['recheck'],
                                   {'bankroll': 1000, 'peak': 1000}, self.case['decision_at'])

    def inbox(self, kind, payload):
        root = Path(self.temp.name) / 'inbox'
        root.mkdir(exist_ok=True)
        (root / 'job.json').write_text(json.dumps(
            {'id': 'audit-job', 'type': kind, 'payload': payload}), encoding='utf-8')
        return root


class ResultChronologyTests(LedgerCase):
    def test_premature_backtest_result_cannot_enter_scoring(self):
        for elapsed in (1, 45 * 60, 90 * 60 - 1):
            with self.subTest(elapsed=elapsed):
                case = deepcopy(self.case)
                end = time(case['sports']['match']['kickoff']) + timedelta(seconds=elapsed)
                case['result'].update(finished_at=end.isoformat(), received_at=end.isoformat())
                with self.assertRaisesRegex(ValueError, 'premature REGULATION_90 FINISHED'):
                    walk_forward([case])

    def test_backtest_accepts_boundary_finished_and_early_scoreless_void(self):
        for status, elapsed, scored in (('FINISHED', 90 * 60, 7), ('VOID', 1, 0)):
            with self.subTest(status=status):
                case = deepcopy(self.case)
                end = time(case['sports']['match']['kickoff']) + timedelta(seconds=elapsed)
                case['result'].update(status=status, finished_at=end.isoformat(), received_at=end.isoformat())
                if status == 'VOID':
                    case['result'].update(home_goals=None, away_goals=None)
                report = walk_forward([case])
                self.assertEqual(report['metrics']['n'], scored)
                self.assertFalse(report['can_certify_release'])
                self.assertEqual(report['BET'], 0)

    def test_premature_finished_never_settles_or_enters_feedback(self):
        prediction = self.capture()
        decision = self.decision(prediction)
        self.service.execution(decision['id'], {
            'id': 'external', 'market': prediction['candidates'][0]['key'],
            'odds': 2.1, 'stake': 10, 'bookmaker': 'SYNTHETIC_BOOK',
            'origin': 'EXTERNAL'}, self.case['decision_at'])
        before = self.repo.db.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]
        for elapsed in (1, 90 * 60 - 1):
            with self.subTest(elapsed=elapsed):
                result = deepcopy(self.case['result'])
                result['finished_at'] = (time(self.case['sports']['match']['kickoff']) +
                                         timedelta(seconds=elapsed)).isoformat()
                result['received_at'] = result['finished_at']
                self.clock[0] = time(result['received_at'])
                with self.assertRaisesRegex(ValueError, 'premature REGULATION_90 FINISHED'):
                    self.service.result(result)
                for table in ('results', 'calibration_history', 'postmatch_reports', 'health_events'):
                    self.assertEqual(self.repo.all(table), [])
                self.assertEqual(self.service.accounting()['settled'], [])
                self.assertEqual(self.repo.db.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0], before)
        result['finished_at'] = (time(self.case['sports']['match']['kickoff']) +
                                 timedelta(minutes=90)).isoformat()
        result['received_at'] = result['finished_at']
        self.clock[0] = time(result['received_at'])
        self.assertEqual(self.service.result(result)['records'], 7)
        self.assertEqual(len(self.service.accounting()['settled']), 1)
        self.assertTrue(self.repo.verify())

    def test_early_void_remains_a_refund_without_probability_feedback(self):
        self.capture()
        result = deepcopy(self.case['result'])
        result.update(status='VOID', home_goals=None, away_goals=None)
        result['finished_at'] = (time(self.case['sports']['match']['kickoff']) +
                                 timedelta(seconds=1)).isoformat()
        result['received_at'] = result['finished_at']
        self.clock[0] = time(result['received_at'])
        self.assertEqual(self.service.result(result)['records'], 0)
        self.assertEqual(self.repo.all('calibration_history'), [])

    def test_premature_history_is_rejected_before_a_probability_seal(self):
        row = self.case['sports']['history'][0]
        row['finished_at'] = (time(row['kickoff']) + timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'premature REGULATION_90 FINISHED'):
            self.capture()
        self.assertEqual(self.repo.all('predictions'), [])

    def test_equivalent_timestamp_offsets_preserve_valid_chronology(self):
        self.capture()
        result = deepcopy(self.case['result'])
        result['finished_at'] = time(result['finished_at']).astimezone(
            timezone(timedelta(hours=3))).isoformat()
        self.clock[0] = time(result['received_at'])
        self.assertEqual(self.service.result(result)['records'], 7)


class IntegrityTests(LedgerCase):
    @contextmanager
    def corrupted(self, table, column, value):
        # Commit the test corruption so the separate read-only snapshot sees it.
        old = self.repo.db.execute(f'SELECT id,{column} FROM {table}').fetchall()
        trigger = self.repo.db.execute('SELECT sql FROM sqlite_master WHERE name=?',
            (table + '_no_update',)).fetchone()[0]
        self.repo.db.execute(f'DROP TRIGGER {table}_no_update')
        try:
            self.repo.db.execute(f'UPDATE {table} SET {column}=?', (value,))
            yield
        finally:
            for identifier, previous in old:
                self.repo.db.execute(f'UPDATE {table} SET {column}=? WHERE id=?', (previous, identifier))
            self.repo.db.execute(trigger)

    def populate(self):
        self.service.reserve(['reserved'], 'HOLDOUT', NOW.isoformat())
        inbox = self.inbox('CAPTURE', {'sports': self.case['sports'], 'markets': self.case['markets']})
        self.assertEqual(process_inbox(self.service, inbox)[0]['status'], 'DONE')
        prediction = self.repo.all('predictions')[0]
        alternate = example(NOW, 'alternate-fixture')
        other = self.service.capture(alternate['sports'], alternate['markets'])
        decision = self.decision(prediction)
        self.service.execution(decision['id'], {
            'id': 'external', 'market': prediction['candidates'][0]['key'],
            'odds': 2.1, 'stake': 10, 'bookmaker': 'SYNTHETIC_BOOK',
            'origin': 'EXTERNAL'}, self.case['decision_at'])
        self.clock[0] = time(self.case['result']['received_at'])
        self.service.result(self.case['result'])
        self.assertTrue(self.repo.verify())
        return prediction, other, decision

    def test_corrupted_metadata_fails_local_and_cloud_checks(self):
        prediction, other, decision = self.populate()
        changes = [
            ('predictions', 'at', '2000-01-01T00:00:00Z'),
            ('predictions', 'match_id', other['sports']['match']['id']),
            ('decisions', 'prediction_id', other['id']),
            ('decisions', 'at', '2000-01-01T00:00:00Z'),
            ('bets', 'at', '2000-01-01T00:00:00Z'),
            ('results', 'at', '2000-01-01T00:00:00Z'),
            ('matches', 'kickoff', '2000-01-01T00:00:00Z'),
            ('matches', 'league', 'WRONG'),
            ('model_versions', 'at', '2000-01-01T00:00:00Z'),
            ('calibration_history', 'at', '2000-01-01T00:00:00Z'),
            ('jobs', 'at', '2000-01-01T00:00:00Z'),
            ('split_assignments', 'at', '2000-01-01T00:00:00Z'),
        ]
        for table, column, value in changes:
            with self.subTest(table=table, column=column):
                with self.corrupted(table, column, value):
                    self.assertFalse(self.repo.verify())
                    with self.assertRaisesRegex(ValueError, f'invalid {table}'):
                        snapshot(self.path)
        self.assertTrue(self.repo.verify())

    def test_equivalent_utc_offsets_do_not_flag_corruption(self):
        self.capture()
        self.repo.db.execute('DROP TRIGGER predictions_no_update')
        self.repo.db.execute('UPDATE predictions SET at=?',
            (NOW.astimezone(timezone(timedelta(hours=3))).isoformat(),))
        self.assertTrue(self.repo.verify())
        self.assertEqual(len(snapshot(self.path)['predictions']), 1)

    def test_malformed_payload_and_audit_reference_fail_closed(self):
        self.capture()
        for table, column, value in (
                ('predictions', 'payload', '{'),
                ('audit_logs', 'payload', '[]')):
            with self.subTest(table=table):
                with self.corrupted(table, column, value):
                    self.assertFalse(self.repo.verify())
                    with self.assertRaises(ValueError):
                        snapshot(self.path)

    def test_verify_cli_returns_failure_for_broken_chain_and_success_for_valid_ledger(self):
        self.capture()
        command = [sys.executable, str(ROOT / 'sefirot.py'), '--db', str(self.path), 'verify']
        valid = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertTrue(json.loads(valid.stdout)['integrity'])
        self.repo.db.execute('DROP TRIGGER audit_logs_no_update')
        self.repo.db.execute("UPDATE audit_logs SET previous_hash='broken' WHERE id=1")
        broken = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(broken.returncode, 2, broken.stderr)
        self.assertFalse(json.loads(broken.stdout)['integrity'])


class AtomicWorkerTests(LedgerCase):
    def test_receipt_failure_rolls_back_capture_decision_result_and_closing(self):
        prediction = self.capture()
        self.clock[0] = time(self.case['decision_at'])
        quote = deepcopy(self.case['quotes'][0])
        quote['phase'] = 'CLOSE'
        operations = [
            ('CAPTURE', {'sports': example(NOW, 'worker-fixture')['sports'], 'markets': self.case['markets']}),
            ('DECIDE', {'prediction_id': prediction['id'], 'quotes': self.case['quotes'],
                        'recheck': self.case['recheck'], 'portfolio': {'bankroll': 1000, 'peak': 1000}}),
            ('CLOSING', {'match_id': self.case['sports']['match']['id'], 'quote': quote}),
            ('RESULT', self.case['result']),
        ]
        original = self.repo.insert
        def fail_receipt(table, *args, **kwargs):
            if table == 'jobs':
                raise sqlite3.OperationalError('simulated receipt failure')
            return original(table, *args, **kwargs)
        for kind, payload in operations:
            with self.subTest(kind=kind):
                inbox = self.inbox(kind, payload)
                if kind == 'RESULT':
                    self.clock[0] = time(self.case['result']['received_at'])
                before = snapshot(self.path)
                with patch.object(self.repo, 'insert', side_effect=fail_receipt):
                    result = process_inbox(self.service, inbox)
                self.assertEqual(result[0]['status'], 'ERROR')
                self.assertEqual(snapshot(self.path), before)
        self.assertEqual(process_inbox(self.service, inbox)[0]['status'], 'DONE')
        self.assertEqual(process_inbox(self.service, inbox)[0]['status'], 'ALREADY_PROCESSED')
        self.assertEqual(len(self.repo.all('results')), 1)

    def test_log_failure_rolls_back_decision_and_receipt_then_retry_commits_once(self):
        prediction = self.capture()
        self.clock[0] = time(self.case['decision_at'])
        inbox = self.inbox('DECIDE', {'prediction_id': prediction['id'], 'quotes': self.case['quotes'],
            'recheck': self.case['recheck'], 'portfolio': {'bankroll': 1000, 'peak': 1000}})
        original = self.repo.log
        def fail_log(event, *args, **kwargs):
            if event == 'INBOX_JOB':
                raise sqlite3.OperationalError('simulated log failure')
            return original(event, *args, **kwargs)
        with patch.object(self.repo, 'log', side_effect=fail_log):
            self.assertEqual(process_inbox(self.service, inbox)[0]['status'], 'ERROR')
        for table in ('decisions', 'odds_snapshots', 'jobs'):
            self.assertEqual(self.repo.all(table), [])
        self.clock[0] += timedelta(seconds=1)
        self.assertEqual(process_inbox(self.service, inbox)[0]['status'], 'DONE')
        self.clock[0] += timedelta(seconds=1)
        self.assertEqual(process_inbox(self.service, inbox)[0]['status'], 'ALREADY_PROCESSED')
        self.assertEqual(len(self.repo.all('decisions')), 1)
        self.assertEqual(len(self.repo.all('jobs')), 1)
        self.assertTrue(self.repo.verify())

    def test_two_runners_cannot_process_one_job_twice(self):
        prediction = self.capture()
        clock = time(self.case['decision_at'])
        inbox = self.inbox('DECIDE', {'prediction_id': prediction['id'], 'quotes': self.case['quotes'],
            'recheck': self.case['recheck'], 'portfolio': {'bankroll': 1000, 'peak': 1000}})
        barrier = threading.Barrier(2)
        def run():
            repo = Repository(self.path)
            try:
                service = Service(repo, clock=lambda: clock)
                barrier.wait(timeout=10)
                return process_inbox(service, inbox)[0]['status']
            finally:
                repo.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(results, ['DONE', 'ALREADY_PROCESSED'])
        self.assertEqual(len(self.repo.all('decisions')), 1)
        self.assertEqual(len(self.repo.all('jobs')), 1)

    def test_savepoint_failure_rolls_back_only_inner_scope(self):
        with self.repo.transaction():
            self.repo.insert('teams', 'outer', {'name': 'outer'})
            with self.assertRaisesRegex(ValueError, 'inner failure'):
                with self.repo.transaction():
                    self.repo.insert('teams', 'inner', {'name': 'inner'})
                    raise ValueError('inner failure')
            self.repo.insert('teams', 'after', {'name': 'after'})
        self.assertCountEqual([row['name'] for row in self.repo.all('teams')], ['outer', 'after'])
        self.assertFalse(self.repo.db.in_transaction)


class PolicyCliTests(unittest.TestCase):
    def test_missing_malformed_and_invalid_policy_return_structured_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'policy.json'
            for content in (None, '{', '[]', '{"max_candidates": 8}'):
                with self.subTest(content=content):
                    if content is not None:
                        path.write_text(content, encoding='utf-8')
                    done = subprocess.run([sys.executable, str(ROOT / 'sefirot.py'),
                        '--policy', str(path), 'demo'], capture_output=True, text=True)
                    self.assertEqual(done.returncode, 2)
                    error = json.loads(done.stderr)
                    self.assertEqual(error['status'], 'ERROR')
                    self.assertEqual(error['decision'], 'PASS')
                    self.assertNotIn('Traceback', done.stderr)


if __name__ == '__main__':
    unittest.main()
