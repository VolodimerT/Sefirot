"""Runtime optimizations must preserve probabilities, ledger gates and chronology."""
import copy
from contextlib import redirect_stdout, redirect_stderr
from datetime import timedelta
import io
import json
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot._payoffs import Market, _score_outcomes, number, probabilities, settle
from sefirot.cli import main
from sefirot.contracts import digest, time
from sefirot.fixtures import example
from sefirot.readiness import inspect_readiness
from sefirot.repository import Repository
from sefirot.service import Service
from test_audit_upgrade import NOW, controlled


def reference_probabilities(market, mass):
    result = {'WIN': 0., 'PUSH': 0., 'LOSS': 0.}
    for (home, away), p in mass.items():
        value = number(p, 'score probability')
        if value < 0:
            raise ValueError('negative probability')
        result[settle(market, home, away)] += value
    if abs(sum(result.values()) - 1) > 1e-8:
        raise ValueError('score mass must sum to one')
    return result['WIN'], result['PUSH'], result['LOSS']


class SettlementCacheTests(unittest.TestCase):
    def test_all_supported_contracts_match_original_accumulation_exactly(self):
        markets = [Market('1X2', s) for s in ('HOME', 'DRAW', 'AWAY')]
        markets += [Market('DOUBLE_CHANCE', s) for s in ('1X', 'X2', '12')]
        markets += [Market('DNB', s) for s in ('HOME', 'AWAY')]
        markets += [Market('BTTS', s) for s in ('YES', 'NO')]
        markets += [Market('HANDICAP', s, line) for s in ('HOME', 'AWAY') for line in (-2., -1.5, -1., -.5, 0., .5, 1., 1.5)]
        markets += [Market(kind, s, line) for kind, sides in
                    (('TOTAL', ('OVER', 'UNDER')), ('TEAM_TOTAL', ('HOME_OVER', 'HOME_UNDER', 'AWAY_OVER', 'AWAY_UNDER')))
                    for s in sides for line in (0., .5, 1., 1.5, 2., 2.5, 3.)]
        rng = random.Random(242)
        for _ in range(4):
            scores = [(h, a) for h in range(9) for a in range(9)]
            rng.shuffle(scores)
            weights = [rng.random() for _ in scores]
            total = sum(weights)
            mass = dict(zip(scores, (w / total for w in weights)))
            for m in markets:
                with self.subTest(market=m.key):
                    self.assertEqual(probabilities(m, mass), reference_probabilities(m, mass))

    def test_cached_integer_scores_do_not_accept_equal_bool_or_float_keys(self):
        m = Market('TOTAL', 'UNDER', .5)
        probabilities(m, {(0, 0): 1.})
        for key in ((False, 0), (0., 0), (0, True), (-1, 0)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                probabilities(m, {key: 1.})

    def test_cached_support_still_validates_every_probability_and_total(self):
        m = Market('1X2', 'DRAW')
        probabilities(m, {(0, 0): 1.})
        for value in (True, -1., float('nan'), float('inf'), .9):
            with self.subTest(value=value), self.assertRaises(ValueError):
                probabilities(m, {(0, 0): value})

    def test_same_support_with_changed_mass_or_order_is_recomputed(self):
        m = Market('DNB', 'HOME')
        for mass in ({(0, 0): .2, (1, 0): .8}, {(0, 0): .7, (1, 0): .3}, {(1, 0): .8, (0, 0): .2}):
            self.assertEqual(probabilities(m, mass), reference_probabilities(m, mass))

    def test_large_support_does_not_fill_bounded_cache(self):
        _score_outcomes.cache_clear()
        m = Market('1X2', 'HOME')
        mass = {(h, 0): 1 / 4100 for h in range(4100)}
        self.assertEqual(probabilities(m, mass), reference_probabilities(m, mass))
        self.assertEqual(_score_outcomes.cache_info().currsize, 0)


class LedgerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(':memory:')
        self.addCleanup(self.repo.close)
        self.clock = [NOW]
        self.svc = Service(self.repo, clock=lambda: self.clock[0])
        self.case = example(NOW)

    def test_exact_retry_skips_probability_calculation(self):
        p = self.svc.capture(self.case['sports'], self.case['markets'])
        before = self.repo.db.total_changes
        with patch('sefirot.service.prepare', side_effect=AssertionError('unexpected recalculation')):
            retry = self.svc.capture(self.case['sports'], self.case['markets'])
        self.assertEqual(digest(p), digest(retry))
        self.assertEqual(self.repo.db.total_changes, before)
        self.assertTrue(self.repo.verify())

    def test_changed_fact_does_not_take_retry_shortcut(self):
        self.svc.capture(self.case['sports'], self.case['markets'])
        changed = copy.deepcopy(self.case['sports'])
        changed['evidence'][0]['observed_at'] = (NOW - timedelta(minutes=5)).isoformat()
        with self.assertRaisesRegex(ValueError, 'explicit revision'):
            self.svc.capture(changed, self.case['markets'])

    def test_changed_market_pool_cannot_reuse_existing_seal(self):
        self.svc.capture(self.case['sports'], self.case['markets'])
        with self.assertRaisesRegex(ValueError, 'shop additional markets'):
            self.svc.capture(self.case['sports'], self.case['markets'][:1])

    def test_indexed_fixture_selection_preserves_order_and_utc_cutoff(self):
        p = self.svc.capture(self.case['sports'], self.case['markets'])
        other = example(NOW, 'unrelated')
        self.svc.capture(other['sports'], other['markets'])
        selected = self.repo.all('predictions', '2026-09-30T15:00:00+03:00', match_id=p['sports']['match']['id'])
        self.assertEqual([r['id'] for r in selected], [p['id']])
        self.assertEqual(self.repo.all('predictions', '2026-09-30T11:59:59.999999+00:00', match_id=p['sports']['match']['id']), [])
        plan = self.repo.db.execute('EXPLAIN QUERY PLAN SELECT payload FROM predictions WHERE match_id=? ORDER BY id', ('m',)).fetchall()
        self.assertTrue(any('predictions_match' in row[3] for row in plan))
        with self.assertRaises(ValueError):
            self.repo.all('predictions', **{'match_id OR 1=1': 'm'})

    def test_result_reads_feedback_once_for_seven_market_monitors(self):
        self.svc.capture(self.case['sports'], self.case['markets'])
        self.clock[0] = time(self.case['result']['received_at'])
        with patch.object(self.svc, '_records', wraps=self.svc._records) as reads:
            result = self.svc.result(self.case['result'])
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(result['records'], 7)
        self.assertTrue(self.repo.verify())

    def test_atomic_bootstrap_keeps_foreign_keys_and_immutable_triggers(self):
        self.assertEqual(self.repo.db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(self.repo.db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], 44)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.insert('matches', 'orphan', {}, home='absent', away='absent', league='l', kickoff=NOW.isoformat())

    def test_failed_bootstrap_rolls_back_partial_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.sqlite'
            with patch('sefirot.repository.SCHEMA', 'CREATE TABLE partial(id TEXT); INVALID SQL;'):
                with self.assertRaises(sqlite3.OperationalError):
                    Repository(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            finally:
                db.close()

    def test_audit_still_rejects_unreferenced_record_and_tampered_hash(self):
        self.svc.capture(self.case['sports'], self.case['markets'])
        self.assertTrue(self.repo.verify())
        self.repo.db.execute('DROP TRIGGER predictions_no_update')
        self.repo.db.execute("UPDATE predictions SET payload='{}'")
        self.assertFalse(self.repo.verify())

    def test_warm_integrity_cache_still_detects_unsigned_predictions(self):
        p = self.svc.capture(self.case['sports'], self.case['markets'])
        self.assertTrue(self.repo.verify())
        p['id'] = 'unsigned'
        self.repo.insert('predictions', p['id'], p, match_id=p['sports']['match']['id'],
                         model_id=p['model_id'], at=p['sealed_at'])
        self.assertFalse(self.repo.verify())

    def test_changed_json_format_retains_original_semantic_binding(self):
        p = self.svc.capture(self.case['sports'], self.case['markets'])
        self.assertTrue(self.repo.verify())
        self.repo.db.execute('DROP TRIGGER predictions_no_update')
        self.repo.db.execute('UPDATE predictions SET payload=? WHERE id=?', (json.dumps(p, indent=2), p['id']))
        self.assertTrue(self.repo.verify())

    def test_external_connection_changes_invalidate_canonical_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'external.sqlite'
            repo = Repository(path)
            writer = None
            try:
                svc = Service(repo, clock=lambda: NOW)
                svc.capture(self.case['sports'], self.case['markets'])
                self.assertTrue(repo.verify())
                writer = sqlite3.connect(path)
                writer.execute('DROP TRIGGER predictions_no_update')
                writer.execute("UPDATE predictions SET payload='{}'")
                writer.commit()
                self.assertFalse(repo.verify())
            finally:
                if writer is not None:writer.close()
                repo.close()


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(':memory:')
        self.addCleanup(self.repo.close)
        self.p, self.case, _, self.context = controlled()
        self.clock = [NOW + timedelta(minutes=2)]
        self.svc = Service(self.repo, clock=lambda: self.clock[0])
        self.addCleanup(patch.stopall)
        patch.object(self.repo, 'get', return_value=self.p).start()
        self.ctx_mock = patch.object(self.svc, 'context', return_value=self.context).start()

    def inspect(self):
        return inspect_readiness(self.svc, self.p['id'], self.clock[0].isoformat())

    def test_ready_for_quote_does_not_mean_betting_permission(self):
        before = copy.deepcopy(self.p)
        out = self.inspect()
        self.assertEqual(out['status'], 'READY_FOR_PRICE_RECHECK')
        self.assertTrue(out['quote_recheck_useful'])
        self.assertFalse(out['monetary_permission'])
        self.assertFalse(out['quotes_read'])
        self.assertEqual(self.p, before)
        self.assertEqual(self.repo.db.total_changes, 0)

    def test_uncalibrated_model_blocks_price_chasing(self):
        self.p['candidates'][0]['calibration'] = 'UNCALIBRATED'
        out = self.inspect()
        self.assertEqual(out['status'], 'BLOCKED_BEFORE_PRICE')
        self.assertFalse(out['quote_recheck_useful'])
        self.assertIn('CALIBRATION_INSUFFICIENT', [b['code'] for b in out['markets'][0]['blockers']])

    def test_missing_holdout_is_visible_before_price(self):
        self.context['releases'] = {}
        out = self.inspect()
        self.assertFalse(out['quote_recheck_useful'])
        self.assertIn('HOLDOUT_UNVALIDATED', [b['code'] for b in out['markets'][0]['blockers']])

    def test_old_snapshot_is_not_presented_as_fresh_recheck(self):
        self.clock[0] = NOW + timedelta(minutes=75)
        out = self.inspect()
        self.assertFalse(out['quote_recheck_useful'])
        self.assertIn('RECHECK_STALE', [b['code'] for b in out['markets'][0]['blockers']])
        self.assertEqual(out['recheck_source'], 'SEALED_SNAPSHOT_NOT_NEW_OBSERVATIONS')

    def test_build_mismatch_and_closed_prematch_never_request_price(self):
        self.p['code_hash'] = 'archived-build'
        self.assertEqual(self.inspect()['status'], 'BUILD_MISMATCH')
        self.ctx_mock.assert_not_called()
        self.clock[0] = time(self.p['sports']['match']['kickoff'])
        self.assertEqual(self.inspect()['status'], 'PREMATCH_CLOSED')
        self.ctx_mock.assert_not_called()

    def test_cli_readiness_does_not_create_missing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite'
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--db', str(path), 'readiness', 'missing']), 2)
            self.assertFalse(path.exists())

    def test_repository_read_only_view_cannot_write_or_migrate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.sqlite'
            writable = Repository(path)
            writable.close()
            before = path.read_bytes()
            readonly = Repository(path, read_only=True)
            try:
                self.assertTrue(readonly.verify())
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.insert('teams', 'a', {'name': 'a'})
            finally:
                readonly.close()
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
