"""Complete prospective views and comparable CLV; no new fitting or betting."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src')]
from sefirot.contracts import digest,time
from sefirot.evaluation import metrics
from sefirot.forward_scorecard import _decision_history,_reliability_table
import test_forward_scorecard as forward_fixture
import test_p0_upgrade as settlement_fixture


class DecisionRegistryTests(unittest.TestCase):
    def setUp(self):forward_fixture.ForwardScorecardTests.setUp(self)
    plan=forward_fixture.ForwardScorecardTests.plan
    collect=forward_fixture.ForwardScorecardTests.collect
    settle=forward_fixture.ForwardScorecardTests.settle
    review=forward_fixture.ForwardScorecardTests.review

    def decide_empty(self,p,hour):
        self.clock[0]=time(forward_fixture.stamp(hour))
        return self.service.decide(p['id'],[],{'checked_at':forward_fixture.stamp(hour),'evidence':p['sports']['evidence']},
                                   {'bankroll':1000.,'peak':1000.},self.service.now())

    def test_no_decision_is_not_pass_and_missing_fixtures_remain_in_denominator(self):
        plan=self.plan(3,False);self.collect(plan);out=self.review(plan)
        self.assertEqual(out['decision_registry']['fixture_status_counts'],{'NO_ORIGINAL_SEAL_DECISION':3})
        self.assertEqual(out['decision_registry']['recorded_decisions'],0)
        self.assertEqual(out['planned_fixtures'],3);self.assertEqual(out['reliability_table'],[])

    def test_all_passes_are_recorded_without_prices_or_results(self):
        plan=self.plan(2);self.collect(plan);p=self.repo.all('predictions')[0]
        self.decide_empty(p,1);self.decide_empty(p,2);out=self.review(plan)
        registry=out['decision_registry'];self.assertEqual(registry['recorded_decisions'],2)
        self.assertEqual(registry['fixture_status_counts'],{'NO_ORIGINAL_SEAL_DECISION':1,'PASS':1})
        self.assertEqual(registry['blocker_fixture_counts']['MISSING_CURRENT_PRICE'],1)
        self.assertEqual(out['scored_fixtures'],0);self.assertEqual(out['planned_fixtures'],2)
        row=next(r for r in out['fixtures'] if r['prediction_id']==p['id'])
        self.assertEqual([d['decision'] for d in row['prematch_decisions']],['PASS','PASS'])
        self.assertFalse(registry['selection_uses_results'])

    def test_future_decision_not_backfilled_to_earlier_cutoff(self):
        plan=self.plan(1);self.collect(plan);p=self.repo.all('predictions')[0]
        self.decide_empty(p,1);self.decide_empty(p,2)
        earlier=self.review(plan,forward_fixture.stamp(1))
        self.assertEqual(earlier['decision_registry']['recorded_decisions'],1)
        self.settle(plan,1);later=self.review(plan)
        self.assertEqual(later['decision_registry']['recorded_decisions'],2)
        self.assertEqual(later['scored_fixtures'],1)
        self.assertEqual(later['fixtures'][0]['decision_status'],'PASS')

    def test_read_view_keeps_fictional_bet_and_pass_events_without_selection_by_outcome(self):
        plan=self.plan(1);self.collect(plan);p=self.repo.all('predictions')[0]
        d=self.decide_empty(p,1)
        # A deliberately fictional bound event tests registry labels, not admission.
        fictional=copy.deepcopy(d);fictional.update(at=forward_fixture.stamp(2),decision='BET',
            selected_market=p['candidates'][0]['key'],**{'class':'B'})
        fictional.pop('id');fictional['id']=digest(fictional)
        with self.repo.transaction():
            self.repo.insert('decisions',fictional['id'],fictional,prediction_id=p['id'],at=fictional['at'])
            self.repo.record_log('decisions',fictional['id'],fictional['at'],fictional)
        rows=_decision_history(self.repo,p,forward_fixture.stamp(2))
        self.assertEqual([r['decision'] for r in rows],['PASS','BET'])
        self.assertEqual(self.repo.all('bets'),[]);self.assertTrue(self.repo.verify())

    def test_invalid_postkickoff_event_cannot_become_a_prematch_registry_row(self):
        plan=self.plan(1);self.collect(plan);p=self.repo.all('predictions')[0]
        d=self.decide_empty(p,1);bad=copy.deepcopy(d);bad['at']=p['sports']['match']['kickoff']
        bad.pop('id');bad['id']=digest(bad)
        with self.repo.transaction():
            self.repo.insert('decisions',bad['id'],bad,prediction_id=p['id'],at=bad['at'])
            self.repo.record_log('decisions',bad['id'],bad['at'],bad)
        with self.assertRaisesRegex(ValueError,'chronology'):_decision_history(self.repo,p,forward_fixture.stamp(7))

    def test_reliability_exports_full_contract_profile_bins_without_certification(self):
        plan=self.plan(2);self.collect(plan);self.settle(plan);out=self.review(plan)
        for field in ('raw','base'):
            for market in plan['markets']:
                from sefirot.markets import market_of
                key=market_of(market).key
                rows=[r for r in out['reliability_table'] if r['market']==key and r['probability_version']==field and r['outcome']=='WIN']
                self.assertEqual(sum(r['n'] for r in rows),2)
                self.assertTrue(all(r['competition_profile']=='LOWER' and not r['certification'] for r in rows))
        self.assertFalse(out['holdout_passed']);self.assertEqual(self.repo.all('validation_runs'),[])


class ReliabilityArithmeticTests(unittest.TestCase):
    def test_probability_one_goes_into_final_bin_and_scores_use_whole_outcome_vector(self):
        rows=[{'raw':[1.,0.,0.],'base':[1.,0.,0.],'outcome':'LOSS'},
              {'raw':[.95,0.,.05],'base':[.95,0.,.05],'outcome':'WIN'}]
        out=_reliability_table(rows,'L','MEN','TOTAL:OVER:2.5')
        bucket=next(r for r in out if r['probability_version']=='base' and r['outcome']=='WIN')
        expected=metrics([r['base'] for r in rows],[2,0])
        self.assertEqual(bucket['bin'],9);self.assertEqual(bucket['n'],2)
        self.assertAlmostEqual(bucket['predicted_mean'],.975);self.assertEqual(bucket['actual_rate'],.5)
        self.assertAlmostEqual(bucket['brier'],expected['brier']);self.assertAlmostEqual(bucket['log_loss'],expected['log_loss'])

    def test_push_bins_remain_distinct_and_empty_observations_do_not_get_zero_error(self):
        rows=[{'raw':[.4,.3,.3],'base':[.4,.3,.3],'outcome':'PUSH'}]
        out=_reliability_table(rows,'L','WOMEN','DNB:HOME')
        push=next(r for r in out if r['probability_version']=='base' and r['outcome']=='PUSH')
        self.assertEqual(push['actual_rate'],1.);self.assertEqual(push['bin'],3)
        self.assertEqual(_reliability_table([],'L','WOMEN','DNB:HOME'),[])


class ComparableClvTests(unittest.TestCase):
    def setUp(self):settlement_fixture.SettlementPipelineTests.setUp(self)
    def tearDown(self):settlement_fixture.SettlementPipelineTests.tearDown(self)
    settle=settlement_fixture.SettlementPipelineTests.settle

    def close(self,odd,minute,line_id):
        return {**self.case['quotes'][0],'phase':'CLOSE','odds':odd,'line_id':line_id,
                'observed_at':(settlement_fixture.NOW+timedelta(minutes=110)).isoformat(),
                'received_at':(settlement_fixture.NOW+timedelta(minutes=minute)).isoformat()}

    def test_report_and_postmatch_use_newest_receipt_when_observation_times_tie(self):
        self.settle();old=self.close(2.,111,'older');new=self.close(1.8,112,'later')
        # Make the old report's first-ID tie choice differ from receipt chronology.
        for i in range(100):
            new['line_id']='later-'+str(i)
            if digest({**old,'match_id':self.d['match_id']})<digest({**new,'match_id':self.d['match_id']}):break
        else:self.fail('could not construct deterministic quote tie')
        self.service.closing(self.d['match_id'],old);self.service.closing(self.d['match_id'],new)
        report=self.service.report();quote=next(r for r in report['clv'] if r['kind']=='DECISION_QUOTE_NOT_EXECUTION')
        execution=next(r for r in report['clv'] if r['kind']=='RECORDED_EXECUTION')
        post=report['postmatch_audits'][0]['candidates'][0]
        self.assertEqual(quote['closing'],1.8);self.assertEqual(execution['closing'],1.8)
        self.assertEqual(quote['clv'],post['quote_clv']);self.assertEqual(execution['clv'],post['executions'][0]['clv'])
        self.assertEqual(self.service.report(self.case['decision_at'])['clv'],[])

    def test_missing_closing_quotes_remain_visible_in_execution_coverage(self):
        self.settle();before=self.service.report()['clv_coverage']
        self.assertEqual(before['RECORDED_EXECUTION'],{'recorded':1,'with_matching_close':0,'missing_close':1,'coverage':0.})
        self.assertEqual(before['DECISION_QUOTE_NOT_EXECUTION']['missing_close'],7)
        self.service.closing(self.d['match_id'],self.close(2.,111,'close'))
        after=self.service.report()['clv_coverage']
        self.assertEqual(after['RECORDED_EXECUTION']['coverage'],1.)
        self.assertEqual(after['DECISION_QUOTE_NOT_EXECUTION']['with_matching_close'],1)
        self.assertEqual(after['DECISION_QUOTE_NOT_EXECUTION']['missing_close'],6)

    def test_other_book_or_contract_does_not_fill_missing_clv(self):
        self.settle();quote=self.close(2.,111,'other');quote['bookmaker']='OTHER_BOOK'
        self.service.closing(self.d['match_id'],quote)
        self.assertEqual(self.service.report()['clv_coverage']['RECORDED_EXECUTION']['missing_close'],1)
