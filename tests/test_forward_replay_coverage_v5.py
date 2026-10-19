"""Original forward cohorts survive reconstruction siblings; packets are fictional."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import digest, time
from sefirot.forward import create_plan, capture_plan, settle_plan, inspect_plan
from sefirot.forward_scorecard import create_scorecard
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import archive_packets, export_sports
from test_operations_upgrade import NOW, packet, row, stamp


class ForwardReplayCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / 'archive'
        self.repo = Repository(Path(self.temp.name) / 'ledger.sqlite')
        self.addCleanup(self.repo.close)
        self.clock = [NOW]
        self.service = Service(self.repo, clock=lambda: self.clock[0])
        target = packet([row(100, status='NS', hours=3, score=(None, None))])
        self.plan = create_plan(self.service, target, {9: 'LOWER'}, source_reliability=.95)
        history = packet([row(10+i, hours=-72-i) for i in range(8)], -1)
        archive_packets([target, history], self.archive, stamp())

    def capture(self):
        capture_plan(self.service, self.plan['id'], self.archive)
        return self.repo.all('predictions')[0]

    def replay(self, original, *, at=4):
        sports = copy.deepcopy(original['sports'])
        sports['as_of'] = stamp(1)
        self.clock[0] = time(stamp(at))
        return self.service.capture(sports, self.plan['markets'], parent=original['id'],
                                    reason='NEW_INFORMATION', replay=True)

    def settle(self):
        self.clock[0] = time(stamp(7))
        return settle_plan(self.service, self.plan['id'], packet([row(100, hours=3, score=(2, 1))], 7))

    def score(self, at=None):
        return create_scorecard(self.service, self.plan['id'], at or self.service.now())

    def test_original_capture_postkickoff_replay_result_preserves_whole_cohort(self):
        original = self.capture()
        replay = self.replay(original)
        self.assertGreater(time(replay['sealed_at']), time(original['sports']['match']['kickoff']))
        before = inspect_plan(self.service, self.plan['id'])
        self.assertEqual(before['counts'], {'AWAITING_RESULT': 1})
        self.settle()
        scorecard = self.score()
        self.assertEqual(scorecard['status_counts'], {'SCORED': 1})
        self.assertEqual(scorecard['fixture_coverage'], 1.)
        self.assertEqual(scorecard['market_observations'], 7)
        self.assertTrue(all(r['prediction_id'] == original['id'] for r in scorecard['observations']))
        self.assertTrue(all(r['prediction_id'] == original['id'] for r in self.repo.all('calibration_history')))
        self.assertEqual(inspect_plan(self.service, self.plan['id'])['counts'], {'SETTLED': 1})
        self.assertEqual(len(self.repo.all('predictions')), 2)
        self.assertFalse(scorecard['holdout_passed'])
        self.assertFalse(scorecard['monetary_permission'])
        self.assertEqual(self.repo.all('bets'), [])
        self.assertTrue(self.repo.verify())

    def test_reconstruction_after_settlement_cannot_erase_original_scorecard(self):
        original = self.capture()
        self.settle()
        before = self.score()
        original_digest = digest(self.repo.get('predictions', original['id']))
        self.replay(original, at=8)
        after = self.score()
        self.assertEqual(after['status_counts'], {'SCORED': 1})
        self.assertEqual(after['observations'], before['observations'])
        self.assertEqual(after['groups'], before['groups'])
        self.assertEqual(digest(self.repo.get('predictions', original['id'])), original_digest)
        self.assertEqual(inspect_plan(self.service, self.plan['id'])['counts'], {'SETTLED': 1})
        self.assertTrue(self.repo.verify())

    def test_genuine_revision_stays_fail_closed_even_with_reconstruction_sibling(self):
        original = self.capture()
        sports = copy.deepcopy(original['sports'])
        sports['as_of'] = stamp(1)
        self.clock[0] = time(stamp(1))
        current = self.service.capture(sports, self.plan['markets'], parent=original['id'], reason='DATA_ERROR')
        self.clock[0] = time(stamp(4))
        later = copy.deepcopy(current['sports'])
        later['as_of'] = stamp(2)
        self.service.capture(later, self.plan['markets'], parent=current['id'], reason='NEW_INFORMATION', replay=True)
        with self.assertRaisesRegex(ValueError, 'incompatible or revised'):
            self.settle()
        self.assertEqual(self.score()['status_counts'], {'INVALID_OR_REVISED_SEAL': 1})
        self.assertEqual(self.score()['observations'], [])
        self.assertEqual(inspect_plan(self.service, self.plan['id'])['counts'], {'INVALID_OR_REVISED_SEAL': 1})
        self.assertTrue(self.repo.verify())

    def test_direct_capture_and_replay_still_require_original_forward_capture_proof(self):
        sports = export_sports(self.archive, 100, stamp(), profile='LOWER', source_reliability=.95)['sports']
        original = self.service.capture(sports, self.plan['markets'])
        self.replay(original)
        self.settle()
        self.assertEqual(self.score()['status_counts'], {'UNVERIFIED_API_CAPTURE': 1})
        self.assertEqual(self.score()['observations'], [])

    def test_reconstruction_only_is_not_an_original_forward_seal(self):
        sports = export_sports(self.archive, 100, stamp(), profile='LOWER', source_reliability=.95)['sports']
        self.clock[0] = time(stamp(4))
        self.service.capture(sports, self.plan['markets'], replay=True)
        with self.assertRaisesRegex(ValueError, 'incompatible or revised'):
            self.settle()
        self.assertEqual(self.score()['status_counts'], {'INVALID_OR_REVISED_SEAL': 1})
        self.assertEqual(inspect_plan(self.service, self.plan['id'])['counts'], {'INVALID_OR_REVISED_SEAL': 1})
        self.assertEqual(self.score()['observations'], [])
        self.assertEqual(self.repo.all('calibration_history'), [])
        self.assertEqual(self.repo.all('results'), [])
        self.assertEqual(self.repo.all('validation_runs'), [])

    def test_cutoff_retains_original_snapshot_before_late_replay_was_available(self):
        original = self.capture()
        self.replay(original)
        before = self.score(stamp(2))
        self.assertEqual(before['status_counts'], {'AWAITING_RESULT': 1})
        self.assertEqual(before['fixtures'][0]['prediction_id'], original['id'])
        self.assertEqual(before['observations'], [])
        self.assertTrue(self.repo.verify())


if __name__ == '__main__':
    unittest.main()
