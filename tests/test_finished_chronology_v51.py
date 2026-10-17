"""No impossible FT feedback/history, and no new authority from a time gate."""
import copy
from datetime import timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.backtesting import walk_forward
from sefirot.contracts import Policy, digest, time
from sefirot.evidence import eligible_history
from sefirot.fixtures import example
from sefirot.football_provider import normalize_sports
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import archive_packets, export_sports
from test_operations_upgrade import NOW, packet, row, stamp


class FinishedChronologyTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(':memory:')
        self.addCleanup(self.repo.close)
        self.clock = [NOW]
        self.service = Service(self.repo, clock=lambda: self.clock[0])
        self.case = example(NOW, 'finished-chronology-v51')

    def result(self, seconds, *, void=False):
        result = copy.deepcopy(self.case['result'])
        end = time(self.case['sports']['match']['kickoff']) + timedelta(seconds=seconds)
        result.update(finished_at=end.isoformat(),received_at=end.isoformat())
        if void:
            result.update(status='VOID',home_goals=None,away_goals=None)
        self.clock[0] = end
        return result

    def test_early_finished_cannot_write_result_feedback_or_audit(self):
        p = self.service.capture(self.case['sports'], self.case['markets'])
        for seconds in (1, 45*60, 90*60-0.000001):
            with self.subTest(seconds=seconds):
                changes = self.repo.db.total_changes
                with self.assertRaises(ValueError):
                    self.service.result(self.result(seconds))
                self.assertEqual(self.repo.db.total_changes, changes)
                self.assertEqual(self.repo.all('results'), [])
                self.assertEqual(self.repo.all('calibration_history'), [])
                self.assertEqual(digest(self.repo.get('predictions',p['id'])),digest(p))
                self.assertTrue(self.repo.verify())

    def test_exact_ninety_minute_finished_still_scores_original(self):
        p = self.service.capture(self.case['sports'], self.case['markets'])
        result = self.result(90*60)
        self.assertEqual(self.service.result(result)['records'],7)
        self.assertEqual({r['prediction_id'] for r in self.repo.all('calibration_history')},{p['id']})
        self.assertEqual(self.service.result(result),{'idempotent':True,'records':0})
        self.assertEqual(self.repo.all('bets'),[])
        self.assertEqual(self.repo.all('policy_approvals'),[])

    def test_late_receipt_is_not_replaced_with_an_invented_whistle_time(self):
        self.service.capture(self.case['sports'], self.case['markets'])
        result = self.result(6*3600)
        self.service.result(result)
        self.assertEqual(self.repo.get('results',result['match_id']),result)

    def test_early_void_remains_scoreless_and_does_not_add_calibration(self):
        self.service.capture(self.case['sports'], self.case['markets'])
        self.assertEqual(self.service.result(self.result(1,void=True))['records'],0)
        self.assertEqual(self.repo.all('calibration_history'),[])
        self.assertEqual(self.repo.all('results')[0]['status'],'VOID')

    def test_void_still_requires_existing_basic_chronology(self):
        self.service.capture(self.case['sports'], self.case['markets'])
        for seconds in (0,-1):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                self.service.result(self.result(seconds,void=True))
        self.assertEqual(self.repo.all('results'),[])

    def test_offsets_are_compared_as_instants_at_the_ninety_minute_boundary(self):
        self.service.capture(self.case['sports'], self.case['markets'])
        result=self.result(90*60)
        result['finished_at']=time(result['finished_at']).astimezone(timezone(timedelta(hours=3))).isoformat()
        self.assertEqual(self.service.result(result)['records'],7)

    def test_received_before_finished_cannot_score_even_after_ninety_minutes(self):
        self.service.capture(self.case['sports'], self.case['markets'])
        result=self.result(91*60)
        result['received_at']=(time(result['finished_at'])-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):self.service.result(result)
        self.assertEqual(self.repo.all('calibration_history'),[])

    def history(self, seconds):
        sports=copy.deepcopy(self.case['sports'])
        h=sports['history'][0]
        end=time(h['kickoff'])+timedelta(seconds=seconds)
        h.update(finished_at=end.isoformat(),received_at=(end+timedelta(seconds=1)).isoformat())
        return sports

    def test_early_history_cannot_enter_features_or_create_a_prediction(self):
        for seconds in (1,45*60,90*60-0.000001):
            sports=self.history(seconds)
            with self.subTest(seconds=seconds):
                with self.assertRaises(ValueError):eligible_history(sports,Policy())
                with self.assertRaises(ValueError):self.service.capture(sports,self.case['markets'])
                self.assertEqual(self.repo.all('predictions'),[])

    def test_exact_ninety_minute_history_keeps_source_timestamp(self):
        sports=self.history(90*60)
        usable,_=eligible_history(sports,Policy())
        self.assertEqual(next(r for r in usable if r['id']=='history-0'),sports['history'][0])

    def test_early_backtest_outcome_cannot_contribute_scores(self):
        for seconds in (1,45*60,90*60-0.000001):
            case=copy.deepcopy(self.case);case['result']=self.result(seconds)
            with self.subTest(seconds=seconds),self.assertRaises(ValueError):walk_forward([case])

    def test_exact_ninety_minute_backtest_is_still_research_only(self):
        case=copy.deepcopy(self.case);case['result']=self.result(90*60)
        report=walk_forward([case])
        self.assertEqual(report['metrics']['n'],7)
        self.assertFalse(report['can_certify_release'])
        self.assertEqual(report['BET'],0)

    def test_early_void_backtest_is_not_a_win_loss_or_calibration_record(self):
        case=copy.deepcopy(self.case);case['result']=self.result(1,void=True)
        report=walk_forward([case])
        self.assertEqual(report['metrics']['n'],0)
        self.assertEqual(report['records'],[])

    def test_provider_quarantines_early_ft_without_inventing_available_at(self):
        target=packet([row(100,status='NS',hours=3,score=(None,None))])
        for minutes in (0,1,45,89):
            history=packet([row(10,hours=-minutes/60)])
            with self.subTest(minutes=minutes):
                out=normalize_sports(target,100,[history],profile='LOWER',source_reliability=.95)
                self.assertEqual(out['sports']['history'],[])
                self.assertEqual(out['receipt']['excluded_history'][0]['reason'],'IMPOSSIBLE_RESULT_CHRONOLOGY')
                self.assertFalse(out['receipt']['monetary_permission'])

    def test_provider_ninety_minute_ft_keeps_actual_receipt_upper_bound(self):
        target=packet([row(100,status='NS',hours=3,score=(None,None))])
        history=packet([row(10,hours=-1.5)])
        out=normalize_sports(target,100,[history],profile='LOWER',source_reliability=.95)
        self.assertEqual(out['sports']['history'][0]['finished_at'],stamp())
        self.assertEqual(out['sports']['history'][0]['received_at'],stamp())

    def export(self, histories, cutoff=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)/'archive'
        target=packet([row(100,status='NS',hours=3,score=(None,None))])
        archive_packets([target,*histories],root,stamp(10))
        before={p.name:p.read_bytes() for p in root.glob('*.json')}
        out=export_sports(root,100,cutoff or stamp(),profile='LOWER',source_reliability=.95)
        self.assertEqual({p.name:p.read_bytes() for p in root.glob('*.json')},before)
        return out

    def test_archive_quarantines_early_first_ft_even_if_later_packet_is_final(self):
        early=packet([row(10,hours=-1)])
        later=packet([row(10,hours=-1)],hours=1)
        out=self.export([early,later],stamp(1))
        self.assertEqual(out['sports']['history'],[])
        self.assertTrue(any(r['reason']=='IMPOSSIBLE_RESULT_CHRONOLOGY' for r in out['receipt']['excluded_history']))

    def test_archive_keeps_valid_first_ninety_minute_receipt(self):
        out=self.export([packet([row(10,hours=-1.5)])])
        self.assertEqual(out['sports']['history'][0]['finished_at'],stamp())


if __name__=='__main__':unittest.main()
