"""Fictional API packets exercise prospective timing and leakage boundaries."""
import copy
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cli import main
from sefirot.contracts import Policy, digest, time
from sefirot.forward import create_plan, capture_plan, settle_plan, inspect_plan
from sefirot.identity import model_code_hash
from sefirot.probability import fit_calibrator
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import archive_packets
from test_operations_upgrade import NOW, packet, row, stamp, reseal


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(':memory:'); self.addCleanup(self.repo.close)
        self.clock = [NOW]
        self.service = Service(self.repo, clock=lambda: self.clock[0])
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / 'archive'
        target = row(100, status='NS', hours=3, score=(None, None))
        self.target = packet([target])
        self.history = packet([row(10 + n, hours=-72 - n) for n in range(8)], -1)

    def plan(self, **kwargs):
        return create_plan(self.service, self.target, {9: 'LOWER'}, source_reliability=.95, **kwargs)

    def collect(self, plan, enough=True):
        archive_packets([self.target] + ([self.history] if enough else []), self.archive, stamp())
        return capture_plan(self.service, plan['id'], self.archive)

    def fit(self, **changes):
        record = {'match_id': 'old-training', 'market': '1X2:HOME', 'kind': '1X2', 'raw_win': .5,
                  'outcome': 'WIN', 'synthetic': False, 'received_at': stamp(-2), 'competition_profile': 'LOWER'}
        artifact = fit_calibrator([record], model_code_hash(), self.service.policy.fingerprint, stamp(-1))
        artifact.update(changes); artifact.pop('hash'); artifact['hash'] = digest(artifact)
        with self.repo.transaction():
            self.repo.insert('calibrators', artifact['hash'], artifact, at=artifact['fit_at'])
            self.repo.record_log('calibrators', artifact['hash'], artifact['fit_at'], artifact)
        return artifact

    def test_reserve_whole_cohort_before_probability_and_never_claim_holdout_success(self):
        self.target = packet([row(100, status='NS', hours=3, score=(None, None)),
            row(101, status='NS', hours=4, score=(None, None)), row(102, league=10, status='NS', hours=5)])
        plan = self.plan()
        self.assertEqual(len(plan['members']), 2)
        self.assertEqual(plan['excluded_counts'], {'OUTSIDE_DECLARED_LEAGUES': 1})
        self.assertEqual(len(self.repo.all('split_assignments')), 2)
        self.assertEqual(self.repo.all('predictions'), [])
        status = inspect_plan(self.service, plan['id'])
        self.assertEqual(status['counts'], {'NO_SEAL': 2})
        self.assertFalse(status['holdout_passed']); self.assertFalse(status['monetary_permission'])
        self.assertTrue(self.repo.verify())

    def test_thin_data_remains_in_denominator_and_no_prior_only_forecast_created(self):
        plan = self.plan(); attempt = self.collect(plan, enough=False)
        self.assertEqual(attempt['counts'], {'INSUFFICIENT_HISTORY': 1})
        self.assertEqual(self.repo.all('predictions'), [])
        self.assertEqual(inspect_plan(self.service, plan['id'])['planned_fixtures'], 1)

    def test_complete_research_capture_api_result_feedback_and_retry(self):
        plan = self.plan(); self.collect(plan)
        first = self.repo.all('predictions')[0]
        self.assertEqual(first['sealed_at'], plan['at'])
        self.assertTrue(first['captured_prematch']); self.assertFalse(first['reconstructed'])
        again = capture_plan(self.service, plan['id'], self.archive)
        self.assertEqual(again['counts'], {'ALREADY_SEALED': 1})
        self.assertEqual(len(self.repo.all('predictions')), 1)
        self.clock[0] = time(stamp(6)); result = packet([row(100, hours=3, score=(2, 0))], 6)
        report = settle_plan(self.service, plan['id'], result)
        self.assertEqual(report['results'][0]['status'], 'SETTLED_API_RESULT')
        self.assertEqual(len(self.repo.all('calibration_history')), 7)
        self.assertEqual(inspect_plan(self.service, plan['id'])['counts'], {'SETTLED': 1})
        settle_plan(self.service, plan['id'], result)
        self.assertEqual(len(self.repo.all('calibration_history')), 7)
        self.assertEqual(self.repo.all('bets'), [])
        self.assertTrue(self.repo.verify())

    def test_missed_window_is_explicit_instead_of_retrospective_prediction(self):
        plan = self.plan(); archive_packets([self.target], self.archive, stamp())
        self.clock[0] = time(stamp(4))
        report = capture_plan(self.service, plan['id'], self.archive)
        self.assertEqual(report['counts'], {'MISSED_PREMATCH_WINDOW': 1})
        self.assertEqual(inspect_plan(self.service, plan['id'])['counts'], {'MISSED_PREMATCH_WINDOW': 1})
        self.assertEqual(self.repo.all('predictions'), [])

    def test_wrong_archive_cannot_supply_unbound_identity(self):
        plan = self.plan(); archive_packets([self.history], self.archive, stamp())
        with self.assertRaisesRegex(ValueError, 'original selection'):capture_plan(self.service, plan['id'], self.archive)

    def test_postponed_kickoff_requires_new_plan_without_quietly_relabeling_fixture(self):
        plan = self.plan(); archive_packets([self.target, self.history], self.archive, stamp())
        changed = packet([row(100, status='NS', hours=5, score=(None, None))], .1)
        self.clock[0] = time(stamp(.2)); archive_packets([changed], self.archive, stamp(.2))
        report = capture_plan(self.service, plan['id'], self.archive)
        self.assertEqual(report['counts'], {'FIXTURE_CHANGED; NEW_PLAN_REQUIRED': 1})
        self.assertEqual(self.repo.all('predictions'), [])

    def test_fit_required_and_synthetic_or_overlapping_fit_rejected(self):
        with self.assertRaisesRegex(ValueError, 'freeze a calibrator'):self.plan(role='HOLDOUT')
        artifact = self.fit(synthetic=True)
        with self.assertRaisesRegex(ValueError, 'nonsynthetic'):self.plan(role='HOLDOUT', calibrator_id=artifact['hash'])
        artifact = self.fit(fit_ids=['api-football:fixture:100'])
        with self.assertRaisesRegex(ValueError, 'overlaps'):self.plan(role='HOLDOUT', calibrator_id=artifact['hash'])
        self.assertEqual(self.repo.all('split_assignments'), [])

    def test_holdout_fit_is_frozen_before_seal_and_cannot_be_used_for_calibration_cohort(self):
        artifact = self.fit()
        with self.assertRaisesRegex(ValueError, 'raw predictions'):self.plan(calibrator_id=artifact['hash'])
        plan = self.plan(role='HOLDOUT', calibrator_id=artifact['hash']); self.collect(plan)
        pred = self.repo.all('predictions')[0]
        self.assertEqual(pred['calibrator']['hash'], artifact['hash'])
        self.assertEqual(inspect_plan(self.service, plan['id'])['counts'], {'AWAITING_RESULT': 1})
        self.assertFalse(inspect_plan(self.service, plan['id'])['holdout_passed'])

    def test_changed_build_cannot_continue_or_resign_old_plan(self):
        plan = self.plan()
        with patch('sefirot.forward.code_hash', return_value='changed'):
            self.assertFalse(inspect_plan(self.service, plan['id'])['same_current_build'])
            with self.assertRaisesRegex(ValueError, 'frozen build'):capture_plan(self.service, plan['id'], self.archive)

    def test_untracked_forecast_with_different_market_pool_is_not_counted_or_settled(self):
        plan = self.plan(); archive_packets([self.target, self.history], self.archive, stamp())
        from sefirot.sports_archive import export_sports
        sports = export_sports(self.archive, 100, stamp(), profile='LOWER', source_reliability=.95)['sports']
        self.service.capture(sports, [{'kind':'DNB','side':'AWAY'}])
        self.assertEqual(inspect_plan(self.service, plan['id'])['counts'], {'INVALID_OR_REVISED_SEAL':1})
        with self.assertRaisesRegex(ValueError, 'incompatible'):capture_plan(self.service, plan['id'], self.archive)
        self.clock[0] = time(stamp(6))
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            settle_plan(self.service, plan['id'], packet([row(100, hours=3)], 6))
        self.assertEqual(self.repo.all('results'), [])

    def test_invalid_second_result_prevents_settling_valid_first_result(self):
        self.target = packet([row(100, status='NS', hours=3, score=(None,None)),
                              row(101, status='NS', hours=4, score=(None,None))])
        plan = self.plan(); self.collect(plan); self.clock[0] = time(stamp(7))
        with self.assertRaisesRegex(ValueError, 'identity'):
            settle_plan(self.service, plan['id'], packet([row(100, hours=3), row(101, home=3, hours=4)], 7))
        self.assertEqual(self.repo.all('results'), [])

    def test_external_plan_modification_is_detected_by_content_bound_journal(self):
        plan = self.plan(); changed = copy.deepcopy(plan); changed['role'] = 'HOLDOUT'
        self.repo.db.execute('DROP TRIGGER jobs_no_update')
        self.repo.db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(changed), plan['id']))
        with self.assertRaisesRegex(ValueError, 'integrity'):inspect_plan(self.service, plan['id'])

    def test_existing_assignments_abort_whole_plan_without_partial_reservations(self):
        self.target = packet([row(100, status='NS', hours=3, score=(None, None)),
                              row(101, status='NS', hours=4, score=(None, None))])
        self.service.reserve(['api-football:fixture:101'], 'MONITOR', stamp())
        with self.assertRaisesRegex(ValueError, 'already assigned'):self.plan()
        self.assertEqual(len(self.repo.all('split_assignments')), 1)
        self.assertEqual(self.repo.all('jobs'), [])

    def test_active_routes_cannot_silently_replace_study_calibrator(self):
        with self.repo.transaction():self.repo.insert('model_routes', 'route', {'id': 'route', 'at': stamp()}, at=stamp())
        with self.assertRaisesRegex(ValueError, 'dedicated research'):self.plan()

    def test_invalid_and_future_target_packets_fail_without_reserving_anything(self):
        for kind in ('result', 'future_receipt', 'plan_error', 'live'):
            target = copy.deepcopy(self.target)
            if kind == 'result':target['data']['response'][0]['score']['fulltime']['home'] = 1
            if kind == 'future_receipt':target['receipt']['received_at'] = stamp(1)
            if kind == 'plan_error':target['data']['errors'] = {'plan': 'denied'}
            if kind == 'live':target['data']['response'][0]['fixture']['status']['short'] = '1H'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                create_plan(self.service, reseal(target), {9:'LOWER'}, source_reliability=.95)
        self.assertEqual(self.repo.all('jobs'), [])

    def test_result_ids_and_regulation_time_are_required_before_any_settlement(self):
        plan = self.plan(); self.collect(plan); self.clock[0] = time(stamp(6))
        wrong = packet([row(100, home=3, hours=3)], 6)
        with self.assertRaisesRegex(ValueError, 'identity'):settle_plan(self.service, plan['id'], wrong)
        for state in ('AET', 'PEN', 'CANC', 'PST', '1H'):
            out = settle_plan(self.service, plan['id'], packet([row(100, status=state, hours=3)], 6))
            self.assertEqual(out['results'][0]['status'], 'AWAITING_REGULATION_FT')
        self.assertEqual(self.repo.all('results'), [])

    def test_correction_is_quarantined_without_overwriting_original_feedback(self):
        plan = self.plan(); self.collect(plan); self.clock[0] = time(stamp(6))
        settle_plan(self.service, plan['id'], packet([row(100, hours=3)], 6))
        before = copy.deepcopy(self.repo.all('calibration_history'))
        with self.assertRaisesRegex(ValueError, 'correction'):
            settle_plan(self.service, plan['id'], packet([row(100, hours=3, score=(0, 0))], 6))
        self.assertEqual(self.repo.all('calibration_history'), before)

    def test_manual_result_cannot_be_relabelled_as_original_forward_api_proof(self):
        plan = self.plan(); self.collect(plan); self.clock[0] = time(stamp(6))
        self.service.result({'match_id':'api-football:fixture:100','status':'FINISHED','home_goals':2,
            'away_goals':1,'finished_at':stamp(5),'received_at':stamp(6),'source':'manual'})
        self.assertEqual(inspect_plan(self.service, plan['id'])['counts'], {'SETTLED_WITHOUT_FORWARD_API_RECEIPT':1})
        with self.assertRaisesRegex(ValueError, 'do not relabel'):
            settle_plan(self.service, plan['id'], packet([row(100, hours=3)], 6))

    def test_interrupted_api_batch_keeps_provenance_and_can_resume(self):
        plan = self.plan(); self.collect(plan); self.clock[0] = time(stamp(6))
        original = self.service.result
        def committed_then_interrupted(result):
            original(result); raise OSError('simulated interruption after commit')
        result = packet([row(100, hours=3)], 6)
        with patch.object(self.service, 'result', side_effect=committed_then_interrupted), self.assertRaises(OSError):
            settle_plan(self.service, plan['id'], result)
        self.assertEqual(inspect_plan(self.service, plan['id'])['counts'], {'SETTLED':1})
        settle_plan(self.service, plan['id'], result)
        self.assertTrue(self.repo.verify()); self.assertEqual(len(self.repo.all('calibration_history')), 7)


class ForwardCliTests(unittest.TestCase):
    def test_readonly_status_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as root, redirect_stderr(io.StringIO()):
            db = Path(root) / 'absent.sqlite'
            self.assertEqual(main(['--db', str(db), 'forward-status', 'unknown']), 2)
            self.assertFalse(db.exists())

    def test_cli_plan_and_status_close_windows_files_and_do_not_overwrite_report(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / 'research.sqlite'; source = Path(root) / 'api.json'; out = Path(root) / 'plan.json'
            source.write_text(json.dumps(packet([row(100, status='NS', hours=3, score=(None,None))])))
            with patch('sefirot.service.Service.now', return_value=stamp()), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                argv = ['--db',str(db),'forward-plan',str(source),'--league-profile','9=LOWER',
                        '--source-reliability','.95','--output',str(out)]
                self.assertEqual(main(argv), 0)
                self.assertEqual(main(argv), 2)
                plan = json.loads(out.read_text())
                self.assertEqual(main(['--db',str(db),'forward-status',plan['id']]), 0)
            with closing(Repository(db, read_only=True)) as repo:self.assertTrue(repo.verify())


if __name__ == '__main__':unittest.main()
