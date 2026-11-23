"""SYNTHETIC_TEST_ONLY: shadow CLI inputs, restart, proofs and settlement."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.football_pipeline import ingest
from research.prospective_shadow import enqueue, fetch_approved, plan_next, render, report, run
from sefirot.contracts import canonical, time
from sefirot.football_gateway import SportsBudgetGateError, SportsGatewayTransportError
from sefirot.forward_scorecard import create_scorecard
from sefirot.repository import Repository
from sefirot.service import Service
from scripts.calibration_quality_audit import audit
from test_football_pipeline import packet
from test_operations_upgrade import row, stamp


class ProspectiveShadowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.db = self.base / 'shadow.sqlite'
        self.sources = Repository(self.base / 'source.sqlite')
        self.addCleanup(self.sources.close)
        self.repo = Repository(self.db)
        self.addCleanup(lambda: self.repo.close())
        self.now = time(stamp())
        self.service = Service(self.repo, clock=lambda: self.now)

    def put(self, rows, receipt=0, *, imported=None, exact=False):
        params = {'id': rows[0]['fixture']['id']} if exact else {'league': 9, 'season': 2030}
        original = packet(params=params, rows=rows, at=stamp(receipt))
        qc = ingest(self.sources, canonical(original).encode(),
                    imported_at=stamp(receipt if imported is None else imported))
        self.assertTrue(qc['accepted'], qc)
        return original

    def upcoming(self, fid=100, hours=3):
        return row(fid, status='NS', hours=hours, score=(None, None))

    def stage(self, *, exact=True, at=0, synthetic=True, fixtures=8):
        rows = [row(i+10, hours=-72-i) for i in range(fixtures)]
        original = self.put([self.upcoming()], at, exact=True) if exact else None
        self.put([self.upcoming(), self.upcoming(101), *rows], at - 0.1)
        task = enqueue(self.service, self.sources, 100, 'MEN', .95, synthetic_test_only=synthetic)
        return task, original

    def tick(self, phase):
        return run(self.service, self.sources, phase)['processed']

    def restart(self):
        self.repo.close()
        self.repo = Repository(self.db)
        self.service = Service(self.repo, clock=lambda: self.now)

    def test_full_cycle_with_restart_and_disputed_result(self):
        task, _ = self.stage()
        self.assertEqual(task, enqueue(self.service, self.sources, 100, 'MEN', .95, synthetic_test_only=True))
        with self.assertRaisesRegex(ValueError, 'different ledgers'):
            enqueue(self.service, self.sources, 101, 'MEN', .95)
        with self.assertRaisesRegex(RuntimeError, 'interrupt'):
            with patch('research.prospective_shadow.capture_plan', side_effect=RuntimeError('interrupt')):
                self.tick('capture')
        self.restart()
        self.assertEqual(self.repo.all('split_assignments'), [])
        state, = self.tick('capture')
        self.assertEqual(state['status'], 'AWAITING_FT')
        self.assertEqual(state['sources'][0]['available_at'] <= state['source_cutoff'], True)
        prediction, = self.repo.all('predictions')
        self.assertEqual(prediction['id'], state['prediction_id'])
        self.assertTrue(prediction['synthetic'])
        self.assertLess(time(prediction['sealed_at']), time(task['match']['kickoff']))
        self.assertEqual(self.tick('capture'), [])
        self.now = time(stamp(6))
        self.assertEqual(self.tick('settle'), [])
        self.put([row(100, hours=3, score=(1, 1))], 6)
        waiting, = self.tick('settle')
        self.assertEqual(waiting['reason'], 'EXACT_FT_RECEIPT_REQUIRED')
        self.put([row(100, hours=3, score=(1, 1))], 6, exact=True)
        with patch('research.prospective_shadow.create_scorecard', side_effect=RuntimeError('interrupted before scorecard')):
            with self.assertRaises(RuntimeError):
                self.tick('settle')
        self.restart()
        self.assertEqual(self.repo.all('results'), [])
        settled, = self.tick('settle')
        self.assertEqual(settled['status'], 'SETTLED')
        card = self.repo.get('jobs', settled['evaluation_id'])['scorecard']
        self.assertTrue(card['synthetic_test_only'])
        self.assertEqual(card['scored_fixtures'], 1)
        self.assertEqual(card['market_observations'], 7)
        with self.assertRaisesRegex(ValueError, 'synthetic scorecard'):
            audit(card)
        self.assertEqual(self.tick('settle'), [])
        self.assertEqual(self.repo.all('predictions'), [prediction])
        read_only_sources = Repository(self.base / 'source.sqlite', read_only=True)
        with closing(read_only_sources), closing(Repository(self.db, read_only=True)) as ledger:
            dashboard = report(Service(ledger, clock=lambda: self.now), read_only_sources)
            self.assertEqual(dashboard['counts'], {'SETTLED': 1})
            self.assertEqual(dashboard['scored_original_fixtures'], 0)
            self.assertIn('SYNTHETIC_TEST_ONLY', render(dashboard))
        with self.assertRaisesRegex(ValueError, 'no longer prematch'):
            self.service.capture(prediction['sports'], prediction['market_pool'], parent=prediction['id'], reason='DATA_ERROR')
        self.now = time(stamp(7))
        self.put([row(100, hours=3, score=(3, 1))], 7, exact=True)
        revised, = self.tick('settle')
        self.assertEqual(revised['status'], 'RESULT_REVIEW')
        self.assertEqual(len(self.repo.all('results')), 1)
        self.assertEqual(report(self.service, self.sources)['metrics'], [])
        revised_card = create_scorecard(self.service, state['plan_id'], self.service.now())
        self.assertEqual(revised_card['scored_fixtures'], 0)
        self.assertEqual(revised_card['fixtures'][0]['status'], 'RESULT_REVIEW')
        self.assertTrue(self.repo.verify())
        self.assertEqual(self.repo.all('bets'), [])

    def test_planner_chooses_only_one_qualified_fixture(self):
        self.put([self.upcoming(100, hours=2), self.upcoming(101), self.upcoming(102, 4),
                  *[row(i+10, hours=-72-i) for i in range(8)]], -.1)
        self.put([self.upcoming(101)], 0, exact=True)
        result = plan_next(self.service, self.sources, 9, 'MEN', .95)
        self.assertEqual([r['status'] for r in result['candidates']], ['NEEDS_DATA', 'QUALIFIED'])
        self.assertEqual(result['selected']['fixture_id'], 101)
        self.assertEqual(len(self.repo.all('jobs')), 1)
        self.assertEqual(self.repo.all('predictions'), [])

    def test_changed_numeric_identity_is_rejected(self):
        self.stage()
        changed = self.upcoming()
        changed['teams']['home']['id'] = 123
        self.put([changed], .1, exact=True)
        self.now = time(stamp(.1))
        refused, = self.tick('capture')
        self.assertEqual(refused['reason'], 'FIXTURE_CHANGED')
        self.assertEqual(self.repo.all('predictions'), [])

    def test_changed_kickoff_rejects_and_stale_remains_pending(self):
        self.stage(at=-48)
        stale, = self.tick('capture')
        self.assertEqual(stale['reason'], 'STALE_TARGET_OBSERVATION')
        self.put([self.upcoming(hours=4)], 0, exact=True)
        changed, = self.tick('capture')
        self.assertEqual(changed['reason'], 'FIXTURE_CHANGED')
        self.assertEqual(self.repo.all('predictions'), [])

    def test_reschedule_after_seal_preserves_original_and_excludes_result(self):
        self.stage()
        self.tick('capture')
        original, = self.repo.all('predictions')
        self.now = time(stamp(.1))
        self.put([self.upcoming(hours=4)], .1, exact=True)
        disputed, = self.tick('settle')
        self.assertEqual(disputed['reason'], 'SEALED_FIXTURE_CHANGED')
        self.assertEqual(self.repo.all('predictions'), [original])
        self.assertEqual(self.repo.all('results'), [])

    def test_no_slicing_calendar_and_no_late_capture(self):
        self.stage(exact=False)
        missing, = self.tick('capture')
        self.assertEqual(missing['reason'], 'EXACT_FIXTURE_RECEIPT_REQUIRED')
        self.now = time(stamp(4))
        late, = self.tick('capture')
        self.assertEqual(late['reason'], 'MISSED_PREMATCH_WINDOW')
        self.assertEqual(self.repo.all('split_assignments'), [])

    def test_receipt_or_import_after_cutoff_cannot_supply_history(self):
        self.stage(fixtures=6)
        self.put([row(25, hours=-60)], -1, imported=1)
        self.put([row(26, hours=-61)], 1)
        thin, = self.tick('capture')
        self.assertIn('INSUFFICIENT_HISTORY', thin['reason'])
        self.assertEqual(thin['history']['home']['eligible_games'], 6)
        self.assertEqual(self.repo.all('predictions'), [])
        self.now = time(stamp(1))
        ready, = self.tick('capture')
        self.assertEqual(ready['status'], 'AWAITING_FT')
        self.assertEqual(ready['history']['home']['eligible_games'], 8)

    def test_historical_ft_revised_before_capture_is_withheld(self):
        self.stage()
        self.put([self.upcoming(10, hours=-72)], .1, exact=True)
        self.now = time(stamp(.1))
        thin, = self.tick('capture')
        self.assertIn('INSUFFICIENT_HISTORY', thin['reason'])
        self.assertEqual(thin['history']['away']['eligible_games'], 7)

    def test_invalid_probability_rolls_back_plan_and_seal(self):
        self.stage()
        save = self.service.capture

        def invalid(*a, **kw):
            pred = deepcopy(save(*a, **kw))
            pred['candidates'][0]['raw'] = [0.8, 0.2, 0.5]
            return pred

        with patch.object(self.service, 'capture', side_effect=invalid) as capture:
            refused, = self.tick('capture')
            self.assertEqual(refused['reason'], 'SHADOW_MODEL_REJECTED')
            self.assertEqual(self.tick('capture'), [])
            self.assertEqual(capture.call_count, 1)
        self.assertEqual(self.repo.all('predictions'), [])
        self.assertEqual(self.repo.all('split_assignments'), [])
        self.assertTrue(self.repo.verify())

    def test_budget_expiry_and_unavailable_gateway_do_not_retry(self):
        self.stage(synthetic=False)
        with patch('scripts.chat_sports_probe.get_sports', side_effect=[
                SportsBudgetGateError('STALE_BUDGET'), SportsGatewayTransportError('UPSTREAM_TIMEOUT')]) as gateway:
            def approved(key, expiry=stamp(.10)):
                return fetch_approved(self.service, self.sources, {'id': 100}, phase='NS',
                                      expires_at=expiry, approval_id=key)
            with self.assertRaisesRegex(ValueError, 'expire within'):
                approved('Expired', stamp(-1))
            self.assertEqual(gateway.call_count, 0)
            self.assertEqual(approved('Attempt1')['reason'], 'SHARED_BUDGET_STALE_BUDGET')
            self.restart()
            with self.assertRaisesRegex(ValueError, 'already used'):
                approved('Attempt1')
            self.assertEqual(approved('Attempt2')['reason'], 'UPSTREAM_TIMEOUT')
            self.assertEqual(gateway.call_count, 2)
            self.assertTrue(all(c.kwargs.get('require_shared_budget') for c in gateway.call_args_list))
        self.assertEqual(report(self.service, self.sources)['api_budget']['status'], 'UPSTREAM_TIMEOUT')

    def test_successful_approved_packet_is_ingested_once(self):
        self.stage(synthetic=False, exact=False)
        upstream = packet(params={'id': 100}, rows=[self.upcoming()], at=stamp())
        with patch('scripts.chat_sports_probe.get_sports', return_value=upstream) as gateway:
            accepted = fetch_approved(self.service, self.sources, {'id': 100}, phase='NS',
                                      expires_at=stamp(.1), approval_id='Once')
            self.assertEqual(accepted['state'], 'DONE')
            self.assertEqual(gateway.call_count, 1)
        state, = self.tick('capture')
        self.assertEqual(state['status'], 'AWAITING_FT')
        card = create_scorecard(self.service, state['plan_id'], self.service.now())
        self.assertEqual(card['scored_fixtures'], 0)
        self.assertNotIn('synthetic_test_only', card)


if __name__ == '__main__':
    unittest.main()
