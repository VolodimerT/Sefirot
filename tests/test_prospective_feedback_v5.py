"""Adverse end-to-end result selection; synthetic fixtures are not model evidence."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import digest, time
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service

NOW = datetime(2026, 10, 12, 21, tzinfo=timezone.utc)


class ProspectiveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / 'ledger.sqlite')
        self.addCleanup(self.repo.close)
        self.clock = [NOW]
        self.service = Service(self.repo, clock=lambda: self.clock[0])
        self.case = example(NOW, match_id='prospective-feedback-v5')

    def capture(self, *, replay=False):
        return self.service.capture(self.case['sports'], self.case['markets'], replay=replay)

    def revision(self, parent, *, seal_minute, snapshot_minute, replay=False):
        sports = copy.deepcopy(parent['sports'])
        sports['as_of'] = (NOW + timedelta(minutes=snapshot_minute)).isoformat()
        self.clock[0] = NOW + timedelta(minutes=seal_minute)
        return self.service.capture(sports, self.case['markets'], parent=parent['id'],
                                    reason='NEW_INFORMATION', replay=replay)

    def settle(self):
        self.clock[0] = time(self.case['result']['received_at'])
        response = self.service.result(self.case['result'])
        return response, self.repo.all('calibration_history')

    def assert_scored(self, rows, prediction, *, prospective):
        self.assertEqual(len(rows), len(prediction['candidates']))
        self.assertTrue(all(r['prediction_id'] == prediction['id'] for r in rows))
        self.assertTrue(all(r['captured_prematch'] is prospective for r in rows))
        self.assertEqual({r['market'] for r in rows}, {c['key'] for c in prediction['candidates']})
        self.assertTrue(self.repo.verify())

    def test_post_kickoff_reconstruction_cannot_shadow_original_prematch(self):
        original = self.capture()
        replay = self.revision(original, seal_minute=121, snapshot_minute=1, replay=True)
        self.assertGreater(time(replay['sealed_at']), time(original['sports']['match']['kickoff']))
        response, rows = self.settle()
        self.assertEqual(response['records'], 7)
        self.assert_scored(rows, original, prospective=True)
        self.assertEqual(digest(self.repo.get('predictions', replay['id'])), digest(replay))
        self.assertEqual(digest(self.repo.get('predictions', original['id'])), digest(original))

    def test_latest_genuine_revision_wins_over_even_later_reconstruction(self):
        original = self.capture()
        current = self.revision(original, seal_minute=1, snapshot_minute=0)
        replay = self.revision(current, seal_minute=121, snapshot_minute=2, replay=True)
        _, rows = self.settle()
        self.assert_scored(rows, current, prospective=True)
        self.assertEqual(len(self.repo.all('predictions')), 3)
        self.assertNotEqual(replay['id'], current['id'])

    def test_reconstruction_sealed_before_kickoff_is_still_not_prospective(self):
        original = self.capture()
        replay = self.revision(original, seal_minute=2, snapshot_minute=1, replay=True)
        self.assertLess(time(replay['sealed_at']), time(original['sports']['match']['kickoff']))
        self.assertTrue(replay['reconstructed'])
        _, rows = self.settle()
        self.assert_scored(rows, original, prospective=True)

    def test_equal_seal_clock_uses_revision_not_lexicographic_prediction_id(self):
        original = self.capture()
        current = self.revision(original, seal_minute=0, snapshot_minute=0)
        self.assertEqual(original['sealed_at'], current['sealed_at'])
        self.assertGreater(current['revision'], original['revision'])
        _, rows = self.settle()
        self.assert_scored(rows, current, prospective=True)

    def test_reconstruction_only_keeps_explicit_existing_research_semantics(self):
        self.clock[0] = NOW + timedelta(minutes=121)
        reconstructed = self.capture(replay=True)
        _, rows = self.settle()
        self.assert_scored(rows, reconstructed, prospective=False)
        self.assertTrue(reconstructed['reconstructed'])
        self.assertEqual(self.repo.all('validation_runs'), [])
        self.assertEqual(self.repo.all('bets'), [])
        self.assertEqual(self.repo.all('policy_approvals'), [])

    def test_result_retry_cannot_rewrite_existing_feedback_or_seals(self):
        original = self.capture()
        _, rows = self.settle()
        before_rows = digest(rows)
        before_prediction = digest(self.repo.get('predictions', original['id']))
        replay = self.revision(original, seal_minute=240, snapshot_minute=1, replay=True)
        self.clock[0] = NOW + timedelta(minutes=241)
        retry = self.service.result(self.case['result'])
        self.assertEqual(retry, {'idempotent': True, 'records': 0})
        self.assertEqual(digest(self.repo.all('calibration_history')), before_rows)
        self.assertEqual(digest(self.repo.get('predictions', original['id'])), before_prediction)
        self.assertEqual(digest(self.repo.get('predictions', replay['id'])), digest(replay))
        self.assertTrue(self.repo.verify())

    def test_void_excludes_both_original_and_reconstructed_probability_scoring(self):
        original = self.capture()
        self.revision(original, seal_minute=121, snapshot_minute=1, replay=True)
        self.case['result'].update(status='VOID', home_goals=None, away_goals=None)
        response, rows = self.settle()
        self.assertEqual(response['records'], 0)
        self.assertEqual(rows, [])
        self.assertEqual(len(self.repo.all('predictions')), 2)
        self.assertTrue(self.repo.verify())


if __name__ == '__main__':
    unittest.main()
