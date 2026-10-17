"""P0 numerical, leakage, admission and immutable settlement regressions."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import Policy, digest, time
from sefirot.engine import prepare, decide, model_code_hash
from sefirot.feedback import validate_stress_classes, brier
from sefirot.fixtures import example
from sefirot.goal_model import (adjusted_rates, frozen_schedule, fit_goal_model,
    validate_artifact, count_marginal, score_distribution)
from sefirot.markets import DEFAULT_POOL, market_of, probabilities, market_reference
from sefirot.probability import estimate, fit_calibrator
from sefirot.repository import Repository
from sefirot.service import Service

NOW=datetime(2026,9,30,12,tzinfo=timezone.utc)
P0=replace(Policy(),goal_model='SOS_THRESHOLD_V2',stress_mode='GRADED')


def artifact(policy=P0):
    train=example(NOW-timedelta(days=200))['sports']
    samples=[]
    for i in range(120):
        date=NOW-timedelta(days=180-i//2)
        samples.append({'match_id':f'cal-{i//2}','league':'SYNTHETIC','competition_profile':'MEN',
                        'side':'home' if i%2==0 else 'away','rate':1.5,'goals':0 if i%3 else 3,
                        'predicted_at':date.isoformat(),'kickoff':(date+timedelta(hours=2)).isoformat(),
                        'received_at':(date+timedelta(hours=5)).isoformat(),
                        'synthetic':True,'reconstructed':False})
    return fit_goal_model(train,samples,policy,(NOW-timedelta(days=100)).isoformat(),model_code_hash())


class StrengthScheduleTests(unittest.TestCase):
    def test_schedule_changes_rates_and_enters_probability(self):
        sports=example(NOW)['sports']
        baseline=estimate(sports,Policy())[2]['rates']
        adjusted=estimate(sports,P0)[2]
        self.assertNotEqual(baseline,adjusted['rates'])
        self.assertTrue(all(t['used_in_probability'] for t in adjusted['schedule_trace']))
        self.assertTrue(any(abs(t['attack_weight']-1)>.01 for t in adjusted['schedule_trace']))

    def test_opponent_strength_has_correct_goal_normalization_direction(self):
        sports=example(NOW)['sports'];rows=[]
        for i in range(12):
            row=copy.deepcopy(sports['history'][i]);row.update(id=f'weak-{i}',home='WEAK',away='OTHER',home_goals=0,away_goals=5)
            rows.append(row)
        target=copy.deepcopy(sports['history'][20]);target.update(id='tested',home='A',away='WEAK',home_goals=3,away_goals=1)
        rows.append(target)
        context=next(t for t in frozen_schedule(rows,P0,{'A'}) if t['history_id']=='tested')
        self.assertLess(context['attack_weight'],1)
        self.assertGreater(context['defense_weight'],1)
        self.assertGreaterEqual(context['attack_weight'],P0.sos_weight_min)
        self.assertLessEqual(context['defense_weight'],P0.sos_weight_max)

    def test_frozen_weights_cannot_see_current_or_future_results(self):
        sports=example(NOW)['sports'];before=frozen_schedule(sports['history'],P0)
        changed=copy.deepcopy(sports);changed['history'][-1]['home_goals']=40
        after=frozen_schedule(changed['history'],P0)
        self.assertEqual(before,after)
        by_id={r['id']:r for r in sports['history']}
        for t in after:
            self.assertNotIn(t['history_id'],t['normalization_ids'])
            self.assertTrue(all(time(by_id[mid]['received_at'])<=time(t['frozen_at']) for mid in t['normalization_ids']))

    def test_late_receipts_are_not_backfilled_into_opponent_weights(self):
        sports=example(NOW)['sports'];sports['history'][0]['received_at']=sports['history'][-1]['received_at']
        trace=frozen_schedule(sports['history'],P0)
        self.assertTrue(all('history-0' not in t['normalization_ids'] for t in trace))

    def test_rolling_prediction_window_does_not_rewrite_frozen_weights(self):
        sports=example(NOW)['sports'];before=adjusted_rates(sports,P0)[1]['schedule_trace']
        later=copy.deepcopy(sports);later['as_of']=(NOW+timedelta(days=680)).isoformat()
        after=adjusted_rates(later,P0)[1]['schedule_trace']
        old={(t['history_id'],t['team']):t for t in before}
        self.assertTrue(after);self.assertLess(len(after),len(before))
        self.assertTrue(all(t==old[(t['history_id'],t['team'])] for t in after))

    def test_same_league_other_profile_cannot_change_sos_forecast(self):
        sports=example(NOW)['sports'];before=estimate(sports,P0)
        other=copy.deepcopy(sports['history'][0]);other.update(id='women',competition_profile='WOMEN',home_goals=40)
        sports['history'].append(other)
        after=estimate(sports,P0)
        self.assertEqual(before[0],after[0])
        self.assertEqual(before[2]['schedule_trace'],after[2]['schedule_trace'])


class LearnedThresholdTests(unittest.TestCase):
    def test_count_distribution_is_learned_and_score_markets_remain_coherent(self):
        fitted=artifact();marginal,_,info=count_marginal(1.5,fitted,P0)
        self.assertEqual(info['status'],'FITTED_COUNT_BIN')
        self.assertGreater(info['buckets'][0],info['raw_buckets'][0])
        self.assertGreater(info['buckets'][3],info['raw_buckets'][3])
        self.assertAlmostEqual(sum(marginal),1)
        mass,_,_=score_distribution(1.5,1.5,fitted,P0)
        self.assertAlmostEqual(sum(mass.values()),1)
        p=probabilities(market_of({'kind':'TEAM_TOTAL','side':'HOME_OVER','line':1.5}),mass)
        self.assertAlmostEqual(p[0],info['buckets'][2]+info['buckets'][3])
        for contract in DEFAULT_POOL:
            self.assertAlmostEqual(sum(probabilities(market_of(contract),mass)),1)

    def test_missing_bin_is_explicit_and_cannot_open_admission(self):
        _,_,info=count_marginal(4.,artifact(),P0)
        self.assertEqual(info['status'],'INSUFFICIENT_COUNT_BIN')
        case=example(NOW);p=prepare(case['sports'],case['markets'],P0)
        self.assertEqual(p['mode'],'UNKNOWN')
        self.assertIn('PROFILE_MODEL_UNFITTED',[i['code'] for i in p['issues']])
        self.assertIn('THRESHOLD_MODEL_UNFITTED',[i['code'] for i in p['issues']])

    def test_artifacts_reject_tamper_wrong_profile_future_fit_and_seen_target(self):
        sports=example(NOW)['sports'];fitted=artifact()
        validate_artifact(fitted,sports,P0,model_code_hash())
        modified=copy.deepcopy(fitted);modified['profile_parameters']['home_prior']=3.
        with self.assertRaisesRegex(ValueError,'hash'):validate_artifact(modified,sports,P0,model_code_hash())
        modified=copy.deepcopy(sports);modified['match']['competition_profile']='WOMEN'
        with self.assertRaisesRegex(ValueError,'profile'):validate_artifact(fitted,modified,P0,model_code_hash())
        modified=copy.deepcopy(sports);modified['as_of']=fitted['fit_at']
        with self.assertRaisesRegex(ValueError,'future fit'):validate_artifact(fitted,modified,P0,model_code_hash())
        modified=copy.deepcopy(sports);modified['match']['id']=fitted['fit_ids'][0]
        with self.assertRaisesRegex(ValueError,'leakage'):validate_artifact(fitted,modified,P0,model_code_hash())

    def test_count_fit_never_accepts_prices_or_overlapping_train_events(self):
        train=example(NOW-timedelta(days=200))['sports'];date=NOW-timedelta(days=150)
        sample={'match_id':'cal','league':'SYNTHETIC','competition_profile':'MEN','side':'home',
                'rate':1.5,'goals':2,'predicted_at':date.isoformat(),'kickoff':(date+timedelta(hours=2)).isoformat(),
                'received_at':(date+timedelta(hours=5)).isoformat(),'synthetic':True,'reconstructed':False}
        for invalid in ({**sample,'odds':2.}, {**sample,'match_id':'history-0'},
                        {**sample,'predicted_at':sample['received_at']}):
            with self.assertRaises(ValueError):fit_goal_model(train,[invalid],P0,NOW.isoformat(),model_code_hash())
        with self.assertRaises(ValueError):fit_goal_model(train,[sample,sample],P0,NOW.isoformat(),model_code_hash())
        with self.assertRaises(ValueError):fit_goal_model({**train,'odds':2.},[sample],P0,NOW.isoformat(),model_code_hash())
        market_train=copy.deepcopy(train);market_train['evidence'][0]['key']='market_news'
        with self.assertRaises(ValueError):fit_goal_model(market_train,[sample],P0,NOW.isoformat(),model_code_hash())

    def test_ordinary_calibrator_is_bound_to_fitted_goal_artifact(self):
        case=example(NOW);fitted=artifact()
        records=[{'match_id':f'x-{i}','market':'TEAM_TOTAL:HOME_OVER:1.5','kind':'TEAM_TOTAL',
                  'competition_profile':'MEN','raw_win':.5,'outcome':'WIN','received_at':fitted['fit_at'],
                  'synthetic':True,'goal_model_hash':'wrong-artifact'} for i in range(25)]
        cal=fit_calibrator(records,model_code_hash(),P0.fingerprint,fitted['fit_at'])
        with self.assertRaisesRegex(ValueError,'another fitted goal'):prepare(case['sports'],case['markets'],P0,cal,fitted)
        records[0]['goal_model_hash']='another'
        with self.assertRaisesRegex(ValueError,'mix'):fit_calibrator(records,model_code_hash(),P0.fingerprint,fitted['fit_at'])

    def test_price_changes_cannot_change_sos_or_threshold_seal(self):
        case=example(NOW);fitted=artifact();before=prepare(case['sports'],case['markets'],P0,goal_model=fitted)
        case['quotes'][0]['odds']=100.
        self.assertEqual(before,prepare(case['sports'],case['markets'],P0,goal_model=fitted))

    def test_synthetic_fit_cannot_be_disguised_with_real_target(self):
        case=example(NOW);case['sports']['synthetic']=False
        p=prepare(case['sports'],case['markets'],P0,goal_model=artifact())
        self.assertTrue(p['synthetic'])
        self.assertIn('GOAL_ARTIFACT_SYNTHETIC_RESEARCH_ONLY',[i['code'] for i in p['issues']])


def graded_case(stress_win=.46,*,class_passed=True):
    policy=replace(Policy(),stress_mode='GRADED')
    case=example(NOW);case['sports']['synthetic']=False
    # The controlled .6 versus .5 boundary needs two independent FACT groups,
    # just as a wider discrepancy does; these are fictional test inputs.
    case['recheck']['evidence'] += [{**e,'id':e['id']+'-independent','source_id':'statistics'}
        for e in case['recheck']['evidence'] if e['key'] in ('lineup','injuries','tactics')]
    p=prepare(case['sports'],[DEFAULT_POOL[0]],policy);p['sealed_at']=NOW.isoformat();p['model_id']='controlled'
    c=p['candidates'][0]
    c.update(base=[.6,0.,.4],low=[.4,0.,.4],high=[.6,0.,.6],calibration='CALIBRATED_BIN',calibration_n=500,
             calibration_low=[.59,0.,.39],calibration_high=[.61,0.,.41],stress_probabilities=[[stress_win,0.,1-stress_win]],
             stress_calibration_statuses=['CALIBRATED_BIN'])
    context={'journal_ok':True,'policy_approved':True,'captured_prematch':True,'exposures':[],
             'health':{c['key']:{'state':'WORKING','trust':'HIGH'}},
             'sephirot_ratings':{c['key']:{role:{'trust':'HIGH'} for role in ('witness','probability','opponent')}},
             'releases':{c['key']:{'passed':True,'stress_classes':{label:{'passed':class_passed}
                       for label in ('ROBUST_VALUE','FRAGILE_VALUE','AGGRESSIVE_VALUE')}}}}
    quotes=[{**case['quotes'][0],'odds':2.}]
    return policy,p,case,quotes,context


def run_graded(case_tuple):
    policy,p,case,quotes,context=case_tuple
    return decide(p,quotes,case['recheck'],case['decision_at'],context,{'bankroll':1000.,'peak':1000.},policy)


class GradedAdmissionTests(unittest.TestCase):
    def test_taunton_pattern_can_be_conditional_after_class_holdout(self):
        d=run_graded(graded_case())
        self.assertEqual(d['decision'],'BET');self.assertEqual(d['verdict'],'playable with conditions')
        self.assertEqual(d['candidates'][0]['stress_grade']['class'],'FRAGILE_VALUE')
        self.assertEqual(d['risk']['stake'],2.5)
        self.assertEqual(d['risk']['probability_bound_basis'],'CALIBRATION_ONLY')
        self.assertNotIn('DEATH_TEST_PRICE_FRAGILITY',[i['code'] for i in d['candidates'][0]['issues']])

    def test_tamworth_pattern_uses_smaller_cap_than_fragile(self):
        robust=run_graded(graded_case(.6));fragile=run_graded(graded_case(.46));aggressive=run_graded(graded_case(.42))
        self.assertEqual(robust['risk']['stake'],5.);self.assertEqual(aggressive['risk']['stake'],1.)
        self.assertLess(aggressive['risk']['stake'],fragile['risk']['stake'])
        self.assertEqual(aggressive['candidates'][0]['stress_grade']['class'],'AGGRESSIVE_VALUE')

    def test_unvalidated_risk_class_cannot_inherit_generic_holdout(self):
        d=run_graded(graded_case(class_passed=False))
        self.assertEqual(d['decision'],'PASS');self.assertEqual(d['risk']['stake'],0.)
        self.assertIn('GRADED_DEATH_TEST_UNVALIDATED',[i['code'] for i in d['candidates'][0]['issues']])

    def test_severe_fragility_remains_a_veto_even_after_class_validation(self):
        d=run_graded(graded_case(.3));self.assertEqual(d['decision'],'PASS')
        self.assertIn('DEATH_TEST_SEVERE_FRAGILITY',[i['code'] for i in d['candidates'][0]['issues']])

    def test_grade_cannot_override_other_critical_gates(self):
        for field in ('journal_ok','policy_approved','captured_prematch'):
            inputs=graded_case();inputs[-1][field]=False
            self.assertEqual(run_graded(inputs)['decision'],'PASS')
        inputs=graded_case();inputs[1]['candidates'][0]['calibration_low']=[0.,0.,0.]
        self.assertEqual(run_graded(inputs)['decision'],'PASS')
        inputs=graded_case();inputs[1]['candidates'][0]['stress_calibration_statuses']=['INSUFFICIENT_BIN']
        self.assertEqual(run_graded(inputs)['decision'],'PASS')

    def test_coach_novelty_and_extreme_divergence_still_require_new_seal(self):
        inputs=graded_case()
        next(e for e in inputs[2]['recheck']['evidence'] if e['key']=='coach')['value']='NEW_COACH'
        self.assertEqual(run_graded(inputs)['mode'],'UNKNOWN')
        self.assertEqual(run_graded(inputs)['decision'],'PASS')
        inputs=graded_case();inputs[1]['candidates'][0]['base']=[.95,0.,.05]
        d=run_graded(inputs);self.assertEqual(d['decision'],'PASS');self.assertEqual(d['mode'],'UNKNOWN')


class StressClassHoldoutTests(unittest.TestCase):
    def records(self):
        rows=[]
        for i in range(200):
            outcome='LOSS' if i%5==0 else 'WIN'
            rows.append({'match_id':str(i),'model_id':'frozen','market':'1X2:HOME','kickoff':(NOW+timedelta(days=i)).isoformat(),
                         'probabilities':[.8,0.,.2],'outcome':outcome,'brier':brier([.8,0.,.2],outcome),
                         'baseline_brier':.25,'baseline_log_loss':.6931471805599453,'ev':.2,'ev_low':.1,
                         'stress_class':'FRAGILE_VALUE','unit_return':.5 if outcome=='WIN' else -1.,
                         'synthetic':False,'captured_prematch':True,'calibration_status':'CALIBRATED_BIN','sports_gates_passed':True})
        return rows

    def test_sufficient_clean_prospective_class_can_pass_without_licensing_other_classes(self):
        out=validate_stress_classes(self.records(),Policy())
        self.assertTrue(out['FRAGILE_VALUE']['passed'])
        self.assertFalse(out['AGGRESSIVE_VALUE']['passed']);self.assertFalse(out['ROBUST_VALUE']['passed'])

    def test_small_reconstructed_uncalibrated_or_bad_facts_never_pass(self):
        self.assertFalse(validate_stress_classes(self.records()[:20],Policy())['FRAGILE_VALUE']['passed'])
        for key,value in (('synthetic',True),('captured_prematch',False),('calibration_status','UNCALIBRATED'),('sports_gates_passed',False),('ev_low',-.01)):
            rows=self.records();rows[0][key]=value
            self.assertFalse(validate_stress_classes(rows,Policy())['FRAGILE_VALUE']['passed'])


class ReferenceConsensusTests(unittest.TestCase):
    def quotes(self):
        q=example(NOW)['quotes'][0];output=[]
        for book,odds in (('sharp-a',(2.,3.,4.)),('sharp-b',(2.2,3.,3.6))):
            for side,price in zip(('HOME','DRAW','AWAY'),odds):
                output.append({**q,'bookmaker':book,'line_id':book,'market':{'kind':'1X2','side':side},'odds':price})
        return output

    def test_only_complete_fresh_designated_lines_form_consensus(self):
        quotes=self.quotes();at=example(NOW)['decision_at']
        ref=market_reference(quotes,quotes[0],.6,0.,reference_bookmakers=('sharp-a','sharp-b'),at=at)
        self.assertEqual(ref['reference_n'],2);self.assertTrue(ref['sharp_consensus'])
        self.assertGreater(ref['dispersion'],0)
        quotes.pop()
        ref=market_reference(quotes,quotes[0],.6,0.,reference_bookmakers=('sharp-a','sharp-b'),at=at)
        self.assertEqual(ref['reference_n'],1);self.assertFalse(ref['sharp_consensus'])

    def test_stale_designated_line_cannot_become_sharp_reference(self):
        quotes=self.quotes();at=example(NOW)['decision_at']
        for q in quotes[3:]:q['observed_at']=(NOW-timedelta(hours=1)).isoformat()
        ref=market_reference(quotes,quotes[0],.6,0.,reference_bookmakers=('sharp-b',),at=at)
        self.assertEqual(ref['method'],'PROPORTIONAL_COMPLETE_BOOKMAKER_LINE');self.assertFalse(ref['sharp_consensus'])


class SettlementPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.repo=Repository(Path(self.temp.name)/'ledger.sqlite')
        self.clock=[NOW];self.service=Service(self.repo,clock=lambda:self.clock[0]);self.case=example(NOW)
        self.p=self.service.capture(self.case['sports'],self.case['markets'])
        self.clock[0]=time(self.case['decision_at'])
        self.d=self.service.decide(self.p['id'],self.case['quotes'],self.case['recheck'],{'bankroll':1000.,'peak':1000.},self.case['decision_at'])
        self.entry={'id':'human','market':self.p['candidates'][0]['key'],'odds':2.2,'stake':5.,'bookmaker':'SYNTHETIC_BOOK','origin':'EXTERNAL'}
        self.service.execution(self.d['id'],self.entry,self.case['decision_at'])

    def tearDown(self):
        self.repo.close();self.temp.cleanup()

    def settle(self,void=False):
        self.clock[0]=time(self.case['result']['received_at'])
        result={**self.case['result']}
        if void:result.update(status='VOID',home_goals=None,away_goals=None)
        return self.service.result(result)

    def test_late_closing_enriches_audit_without_rewriting_snapshot(self):
        self.settle();original=self.repo.all('postmatch_reports')
        c=self.service.settlement_audits()[0]['candidates'][0]
        self.assertEqual(c['entry_odds'],2.2);self.assertEqual(c['decision_odds'],2.1)
        self.assertIsNone(c['closing_odds']);self.assertEqual(c['postmortem_category'],'UNKNOWN')
        self.assertEqual(c['executions'][0]['payout'],11.);self.assertEqual(c['executions'][0]['pnl'],6.)
        quote={**self.case['quotes'][0],'phase':'CLOSE','odds':2.,'observed_at':(NOW+timedelta(minutes=110)).isoformat(),
               'received_at':(NOW+timedelta(minutes=111)).isoformat()}
        self.service.closing(self.d['match_id'],quote)
        c=self.service.report()['postmatch_audits'][0]['candidates'][0]
        self.assertAlmostEqual(c['quote_clv'],.05);self.assertAlmostEqual(c['executions'][0]['clv'],.1)
        self.assertEqual(c['closing_odds'],2.)
        self.assertEqual(original,self.repo.all('postmatch_reports'));self.assertTrue(self.repo.verify())
        self.assertEqual(self.service.settlement_audits(),self.service.settlement_audits())

    def test_void_returns_stake_and_result_retry_is_idempotent(self):
        self.settle(void=True);c=self.service.settlement_audits()[0]['candidates'][0]
        self.assertEqual(c['outcome'],'VOID');self.assertEqual(c['executions'][0]['pnl'],0.)
        self.assertEqual(c['executions'][0]['payout'],5.)
        self.assertTrue(self.settle(void=True)['idempotent']);self.assertTrue(self.repo.verify())

    def test_premise_reviews_are_evidence_based_and_added_in_view(self):
        self.settle()
        review={'market':self.entry['market'],'decision_quality':'UNDETERMINED','causes':['UNKNOWN'],'roles':{},'notes':'review',
                'category':'UNKNOWN','premise_observations':[{'premise_id':'fact-tactics','status':'HELD','evidence':['report-1']}]}
        self.service.postmortem(self.d['id'],review,self.clock[0].isoformat())
        c=self.service.settlement_audits()[0]['candidates'][0]
        self.assertEqual(c['premise_assessment'],'REVIEWED')
        tactic=next(f for f in c['factual_premises'] if f['id']=='fact-tactics')
        self.assertEqual(tactic['assessment']['status'],'HELD');self.assertEqual(c['quality'],'UNDETERMINED')


if __name__=='__main__':unittest.main()
