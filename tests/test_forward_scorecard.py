"""Fictional API cohorts verify coverage, provenance and frozen-score evaluation."""
import copy
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.cli import main
from sefirot.contracts import digest, time
from sefirot.evaluation import log_loss
from sefirot.feedback import brier
from sefirot.forward import create_plan, capture_plan, settle_plan
from sefirot.forward_scorecard import create_scorecard, render_scorecard, _history_reference
from sefirot.markets import market_of
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import archive_packets, export_sports
from test_operations_upgrade import NOW, packet, row, stamp


class ForwardScorecardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.archive = self.root/'archive'
        self.repo = Repository(self.root/'research.sqlite'); self.addCleanup(self.repo.close)
        self.clock = [NOW]; self.service = Service(self.repo, clock=lambda: self.clock[0])

    def plan(self, n=2, enough=True):
        target = packet([row(100+i, status='NS', hours=3+i, score=(None, None)) for i in range(n)])
        plan = create_plan(self.service, target, {9:'LOWER'}, source_reliability=.95)
        history = packet([row(10+i, hours=-72-i) for i in range(8)], -1)
        archive_packets([target]+([history] if enough else []), self.archive, stamp())
        return plan

    def collect(self, plan): return capture_plan(self.service, plan['id'], self.archive)

    def settle(self, plan, n=2, score=(2,1)):
        self.clock[0] = time(stamp(7))
        return settle_plan(self.service, plan['id'], packet([row(100+i, hours=3+i, score=score) for i in range(n)], 7))

    def review(self, plan, at=None): return create_scorecard(self.service, plan['id'], at or self.service.now())

    def test_no_results_have_null_metrics_and_all_planned_matches_remain(self):
        plan=self.plan(3,False); self.collect(plan); out=self.review(plan)
        self.assertEqual(out['planned_fixtures'],3); self.assertEqual(out['scored_fixtures'],0)
        self.assertEqual(out['last_capture_status_counts'],{'INSUFFICIENT_HISTORY':3})
        self.assertTrue(all(g['base']['brier'] is None for g in out['groups']))
        self.assertEqual(out['status'],'NO_SCORABLE_API_RESULTS')
        self.assertFalse(out['holdout_passed']); self.assertFalse(out['statistical_profitability_proven'])

    def test_seven_contracts_are_not_seven_independent_matches(self):
        plan=self.plan(); self.collect(plan); self.settle(plan); out=self.review(plan)
        self.assertEqual(out['scored_fixtures'],2); self.assertEqual(out['market_observations'],14)
        self.assertEqual(len(out['groups']),7)
        self.assertTrue(all(g['base']['n']==2 and g['coverage']==1 for g in out['groups']))
        self.assertTrue(all(g['market_reference'] is None for g in out['groups']))
        self.assertEqual(out['forecasts_recomputed'],0)

    def test_partial_results_and_missed_games_stay_in_denominator(self):
        plan=self.plan(3); self.collect(plan); self.settle(plan,n=1); out=self.review(plan)
        self.assertEqual(out['status_counts'],{'AWAITING_RESULT':2,'SCORED':1})
        self.assertEqual(out['fixture_coverage'],1/3)
        self.assertTrue(all(g['planned_fixtures']==3 and g['scored_fixtures']==1 for g in out['groups']))

    def test_known_future_results_and_jobs_are_not_visible_at_earlier_cutoff(self):
        plan=self.plan(); self.collect(plan); self.settle(plan)
        out=self.review(plan,stamp(2))
        self.assertEqual(out['status_counts'],{'AWAITING_RESULT':2})
        self.assertEqual(out['observations'],[])
        self.assertTrue(all(g['frozen_history_reference']['n']==0 for g in out['groups']))

    def test_future_and_pre_plan_cutoffs_rejected(self):
        plan=self.plan()
        for at in (stamp(-1),stamp(1)):
            with self.assertRaises(ValueError): self.review(plan,at)

    def test_stored_probabilities_match_metrics_without_recomputing_forecast(self):
        plan=self.plan(1); self.collect(plan); self.settle(plan,n=1); out=self.review(plan)
        prediction=self.repo.all('predictions')[0]
        candidate=next(c for c in prediction['candidates'] if c['key']=='TOTAL:OVER:2.5')
        group=next(g for g in out['groups'] if g['market']==candidate['key'])
        self.assertAlmostEqual(group['base']['brier'],brier(candidate['base'],'WIN'))
        self.assertAlmostEqual(group['base']['log_loss'],log_loss(candidate['base'],0))
        self.assertEqual(group['base']['classwise'][0]['reliability'][0]['frequency'],1.)

    def test_push_is_a_separate_outcome_and_half_line_push_mass_stays_zero(self):
        plan=self.plan(1); self.collect(plan); self.settle(plan,n=1,score=(1,1)); out=self.review(plan)
        dnb=next(g for g in out['groups'] if g['market']=='DNB:HOME')
        self.assertEqual(dnb['outcomes'],{'PUSH':1})
        self.assertTrue(all(r['raw'][1]==0 for r in out['observations'] if r['market'] in ('BTTS:YES','TOTAL:OVER:2.5')))

    def test_manual_result_is_not_scored_even_with_api_looking_source_string(self):
        plan=self.plan(1); self.collect(plan); self.clock[0]=time(stamp(7))
        self.service.result({'match_id':'api-football:fixture:100','status':'FINISHED','home_goals':2,'away_goals':1,
            'finished_at':stamp(6),'received_at':stamp(7),'source':'API_FOOTBALL_V3:'+('a'*64)})
        out=self.review(plan)
        self.assertEqual(out['status_counts'],{'UNVERIFIED_API_RESULT':1}); self.assertEqual(out['observations'],[])

    def test_direct_capture_without_forward_api_receipts_is_unverified(self):
        plan=self.plan(1)
        sports=export_sports(self.archive,100,stamp(),profile='LOWER',source_reliability=.95)['sports']
        self.service.capture(sports,plan['markets']); self.settle(plan,n=1)
        self.assertEqual(self.review(plan)['status_counts'],{'UNVERIFIED_API_CAPTURE':1})

    def test_revised_or_synthetic_seal_is_not_counted(self):
        plan=self.plan(1); self.collect(plan)
        p=self.repo.all('predictions')[0]; sports=copy.deepcopy(p['sports'])
        self.clock[0]=time(stamp(1)); sports['as_of']=stamp(1); sports['history'][0]['home_goals']=3
        self.service.capture(sports,plan['markets'],parent=p['id'],reason='DATA_ERROR')
        self.assertEqual(self.review(plan)['status_counts'],{'INVALID_OR_REVISED_SEAL':1})

    def test_archived_build_can_be_read_but_probabilities_are_never_relabelled(self):
        plan=self.plan(1); self.collect(plan); self.settle(plan,n=1)
        with patch('sefirot.forward_scorecard.code_hash',return_value='new-report-build'):
            out=self.review(plan)
        self.assertFalse(out['same_current_build']); self.assertEqual(out['scored_fixtures'],1)
        self.assertEqual(out['frozen_build']['code_hash'],plan['code_hash'])
        self.assertIn('Архивная сборка',render_scorecard(out))

    def test_incompatible_settlement_code_cannot_score_archived_plan(self):
        plan=self.plan(1)
        with patch('sefirot.forward_scorecard.model_code_hash',return_value='changed-probability-code'),self.assertRaisesRegex(ValueError,'compatible archived'):
            self.review(plan)

    def test_history_reference_uses_only_frozen_ids_and_not_target_result(self):
        plan=self.plan(1); self.collect(plan); p=self.repo.all('predictions')[0]
        market=market_of({'kind':'TOTAL','side':'OVER','line':2.5})
        before=_history_reference(p,market)
        p['sports']['history'].append({'id':'late-not-used','kickoff':stamp(4),'received_at':stamp(6),'home_goals':50,'away_goals':50})
        self.assertEqual(_history_reference(p,market),before)
        self.assertAlmostEqual(before['probabilities'][0],9/10)
        self.assertEqual(before['probabilities'][1],0.)

    def test_empty_history_is_not_misrepresented_as_league_baseline(self):
        plan=self.plan(1); self.collect(plan); p=self.repo.all('predictions')[0]
        p['model']['used_history']=[]
        self.assertIsNone(_history_reference(p,market_of({'kind':'BTTS','side':'YES'})))

    def test_missing_duplicate_and_future_frozen_history_rejected(self):
        plan=self.plan(1); self.collect(plan); original=self.repo.all('predictions')[0]
        for kind in ('missing','duplicate','future'):
            p=copy.deepcopy(original)
            if kind=='missing':p['model']['used_history'].append('absent')
            if kind=='duplicate':p['model']['used_history'].append(p['model']['used_history'][0])
            if kind=='future':p['sports']['history'][0]['received_at']=stamp(1)
            with self.subTest(kind=kind),self.assertRaises(ValueError):_history_reference(p,market_of({'kind':'BTTS','side':'YES'}))

    def test_integrity_tampering_is_detected_before_any_scoring(self):
        plan=self.plan(1); self.collect(plan)
        changed=self.repo.all('predictions')[0]; changed['synthetic']=True
        self.repo.db.execute('DROP TRIGGER predictions_no_update')
        self.repo.db.execute('UPDATE predictions SET payload=?',(json.dumps(changed),))
        with self.assertRaisesRegex(ValueError,'integrity'):self.review(plan)

    def test_report_is_repeatable_and_does_not_modify_ledger(self):
        plan=self.plan(1); self.collect(plan); self.settle(plan,n=1)
        before=(self.root/'research.sqlite').read_bytes()
        a=self.review(plan); b=self.review(plan)
        self.assertEqual(a,b); self.assertEqual((self.root/'research.sqlite').read_bytes(),before)
        self.assertFalse(a['monetary_permission']); self.assertEqual(self.repo.all('validation_runs'),[])

    def test_elapsed_collection_accepts_seal_between_attempt_start_and_job_finish(self):
        plan=self.plan(1)
        original=self.service.capture
        def delayed(*args,**kwargs):
            self.clock[0]+=timedelta(seconds=1)
            out=original(*args,**kwargs)
            self.clock[0]+=timedelta(seconds=1)
            return out
        with patch.object(self.service,'capture',side_effect=delayed):self.collect(plan)
        self.settle(plan,n=1)
        self.assertEqual(self.review(plan)['scored_fixtures'],1)

    def test_cli_is_read_only_has_text_and_refuses_overwrite(self):
        plan=self.plan(1); self.collect(plan); self.settle(plan,n=1)
        db=self.root/'research.sqlite'; out=self.root/'scorecard.json'; before=db.read_bytes()
        with patch('sefirot.service.Service.now',return_value=stamp(7)),redirect_stdout(io.StringIO()) as stdout,redirect_stderr(io.StringIO()):
            args=['--db',str(db),'forward-scorecard',plan['id'],'--output',str(out),'--text']
            self.assertEqual(main(args),0); self.assertEqual(main(args),2)
        self.assertIn('оценено 1/1',stdout.getvalue()); self.assertEqual(db.read_bytes(),before)
        self.assertEqual(json.loads(out.read_text())['scored_fixtures'],1)

    def test_cli_does_not_create_absent_database(self):
        db=self.root/'absent.sqlite'
        with redirect_stderr(io.StringIO()):self.assertEqual(main(['--db',str(db),'forward-scorecard','unknown']),2)
        self.assertFalse(db.exists())

    def test_leagues_and_profiles_are_not_pooled_into_one_score(self):
        target=packet([row(100,status='NS',hours=3,score=(None,None)),
                       row(101,league=10,status='NS',hours=4,score=(None,None))])
        plan=create_plan(self.service,target,{9:'LOWER',10:'WOMEN'},source_reliability=.95)
        history=packet([*[row(10+i,hours=-72-i) for i in range(8)],
                        *[row(20+i,league=10,hours=-72-i) for i in range(8)]],-1)
        archive_packets([target,history],self.archive,stamp());self.collect(plan)
        self.clock[0]=time(stamp(7))
        settle_plan(self.service,plan['id'],packet([row(100,hours=3),row(101,league=10,hours=4)],7))
        out=self.review(plan)
        self.assertEqual(len(out['groups']),14)
        self.assertEqual({g['competition_profile'] for g in out['groups']},{'LOWER','WOMEN'})
        self.assertTrue(all(g['planned_fixtures']==1 and g['base']['n']==1 for g in out['groups']))

    def test_void_remains_in_coverage_without_fake_loss_or_metrics(self):
        plan=self.plan(1);self.collect(plan);self.clock[0]=time(stamp(7))
        self.service.result({'match_id':'api-football:fixture:100','status':'VOID','home_goals':None,
                            'away_goals':None,'finished_at':stamp(6),'received_at':stamp(7),'source':'reported void'})
        out=self.review(plan)
        self.assertEqual(out['status_counts'],{'VOID_NOT_SCORED':1})
        self.assertEqual(out['market_observations'],0);self.assertEqual(out['planned_fixtures'],1)
