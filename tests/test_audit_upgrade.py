"""Audit-inspired contract regressions; controlled inputs are not real forecasts."""
import copy
import json
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import Policy,time
from sefirot.engine import prepare,decide,code_hash
from sefirot.evidence import eligible_history
from sefirot.feedback import context_key,ratings
from sefirot.fixtures import example
from sefirot.markets import DEFAULT_POOL,market_of,market_reference,probabilities,settle
from sefirot.probability import distribution,goal_thresholds,grade_stress,schedule_trace,fit_calibrator,calibrate
from sefirot.repository import Repository
from sefirot.retrospective import audit_cases
from sefirot.service import Service

NOW=datetime(2026,9,30,12,tzinfo=timezone.utc)
ROOT=Path(__file__).resolve().parents[1]


def controlled(markets=None,win=.8,odds=1.5):
    case=example(NOW);case['sports']['synthetic']=False
    markets=markets or [DEFAULT_POOL[0]]
    prediction=prepare(case['sports'],markets,Policy());prediction['sealed_at']=NOW.isoformat();prediction['model_id']='controlled-model'
    context={'journal_ok':True,'health':{},'releases':{},'policy_approved':True,'captured_prematch':True,'exposures':[],'sephirot_ratings':{}}
    quotes=[]
    for c in prediction['candidates']:
        c.update(base=[win,0.,1-win],low=[win-.02,0.,max(0,1-win-.02)],high=[min(1,win+.02),0.,1-win+.02],
                 calibration='CALIBRATED_BIN',stress_probabilities=[[win,0.,1-win]])
        context['health'][c['key']]={'state':'WORKING','trust':'HIGH'};context['releases'][c['key']]={'passed':True}
        context['sephirot_ratings'][c['key']]={role:{'trust':'HIGH'} for role in ('witness','probability','opponent')}
        quotes.append({**case['quotes'][0],'market':c['market'],'odds':odds})
    case['recheck']['evidence'] += [{**e,'id':e['id']+'-independent','source_id':'statistics'} for e in case['recheck']['evidence'] if e['key'] in ('lineup','injuries','tactics')]
    return prediction,case,quotes,context


def decision(p,case,quotes,context):
    return decide(p,quotes,case['recheck'],case['decision_at'],context,{'bankroll':1000.,'peak':1000.},Policy())


class ProfileTests(unittest.TestCase):
    def test_profiles_never_mix_history_even_with_same_league(self):
        case=example(NOW);sport=case['sports'];sport['match']['competition_profile']='WOMEN'
        self.assertEqual(eligible_history(sport,Policy())[0],[])
        sport['history'][0]['competition_profile']='WOMEN'
        self.assertEqual([r['id'] for r in eligible_history(sport,Policy())[0]],['history-0'])

    def test_unknown_profile_blocks_without_silently_assuming_men(self):
        case=example(NOW);case['sports']['match'].pop('competition_profile')
        p=prepare(case['sports'],case['markets'],Policy())
        self.assertEqual(p['mode'],'UNKNOWN');self.assertEqual(p['model']['competition_profile'],'UNKNOWN')
        self.assertIn('COMPETITION_PROFILE_UNKNOWN',[i['code'] for i in p['issues']])
        case['sports']['match']['competition_profile']='INVALID'
        with self.assertRaises(ValueError):prepare(case['sports'],case['markets'],Policy())

    def test_profile_calibration_bins_do_not_borrow_other_populations(self):
        records=[{'match_id':str(i),'market':'1X2:HOME','kind':'1X2','raw_win':.5,'outcome':'WIN',
                  'received_at':NOW.isoformat(),'synthetic':True,'competition_profile':'MEN'} for i in range(30)]
        artifact=fit_calibrator(records,'m','p',NOW.isoformat())
        self.assertEqual(calibrate(market_of({'kind':'1X2','side':'HOME'}),[.5,0,.5],artifact,Policy(),'MEN')['status'],'CALIBRATED_BIN')
        for profile in ('WOMEN','RESERVE','LOWER','UNKNOWN'):
            self.assertEqual(calibrate(market_of({'kind':'1X2','side':'HOME'}),[.5,0,.5],artifact,Policy(),profile)['status'],'INSUFFICIENT_BIN')

    def test_context_and_sephira_history_are_profile_specific(self):
        self.assertNotEqual(context_key('L','TOTAL:OVER:2.5','B','M','MEN'),context_key('L','TOTAL:OVER:2.5','B','M','WOMEN'))
        reports=[{'league':'L','kind':'TOTAL','scenario':'B','model_id':'M','competition_profile':'MEN',
                  'match_id':str(i),'at':NOW.isoformat(),'roles':{'probability':{'correct':True,'severe':False}}} for i in range(35)]
        self.assertEqual(ratings(reports,'L','TOTAL','B',Policy(),'M','WOMEN')['probability']['n'],0)

    def test_sos_features_are_frozen_before_each_historic_kickoff(self):
        sport=example(NOW)['sports'];before=schedule_trace(sport,Policy())
        changed=copy.deepcopy(sport);changed['history'][-1]['home_goals']=40
        after=schedule_trace(changed,Policy())
        self.assertEqual(before[:-2],after[:-2])
        by_id={r['id']:r for r in sport['history']}
        for trace in after:
            self.assertNotIn(trace['history_id'],trace['used_ids']);self.assertFalse(trace['used_in_probability'])
            self.assertTrue(all(time(by_id[mid]['received_at'])<=time(trace['frozen_at']) for mid in trace['used_ids']))

    def test_late_received_opponent_results_are_not_backfilled(self):
        sport=example(NOW)['sports'];sport['history'][0]['received_at']=sport['history'][-1]['received_at']
        trace=schedule_trace(sport,Policy())
        self.assertTrue(all('history-0' not in t['used_ids'] for t in trace))


class ProbabilityProjectionTests(unittest.TestCase):
    def test_team_thresholds_are_coherent_with_score_market_probabilities(self):
        mass,_=distribution(1.7,1.2);thresholds=goal_thresholds(mass)
        for side in ('home','away'):
            t=thresholds[side];self.assertAlmostEqual(t['p0']+t['p1']+t['p2_plus'],1)
            self.assertGreaterEqual(t['p2_plus'],t['p3_plus'])
            m=market_of({'kind':'TEAM_TOTAL','side':side.upper()+'_OVER','line':1.5})
            self.assertAlmostEqual(t['p2_plus'],probabilities(m,mass)[0])

    def test_thresholds_reject_bad_mass_and_scores(self):
        for mass in ({},{(0,0):.5},{(-1,0):1.},{(True,0):1.},{(0,0):float('nan')}):
            with self.assertRaises(ValueError):goal_thresholds(mass)

    def test_tamworth_and_taunton_risk_classes_and_boundaries(self):
        cases=[(.0305,-.132,'AGGRESSIVE_VALUE'),(.1273,-.0613,'FRAGILE_VALUE'),(.02,-.10,'FRAGILE_VALUE'),
               (.02,0.,'ROBUST_VALUE'),(.01999,.2,'NO_VALUE')]
        for ev,stress,label in cases:
            grade=grade_stress(ev,stress);self.assertEqual(grade['class'],label);self.assertFalse(grade['monetary_permission'])
        with self.assertRaises(ValueError):grade_stress(float('nan'),0)

    def test_research_stress_grade_does_not_override_admission(self):
        p,case,q,context=controlled();p['candidates'][0]['stress_probabilities']=[[.5,0,.5]]
        out=decision(p,case,q,context)
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['risk']['stake'],0.)
        self.assertEqual(out['candidates'][0]['stress_grade']['class'],'AGGRESSIVE_VALUE')


class MarketRiskTests(unittest.TestCase):
    def test_complete_line_devig_and_single_price_proxy_are_distinct(self):
        quote={**example(NOW)['quotes'][0],'line_id':'line'}
        quotes=[{**quote,'market':{'kind':'1X2','side':side},'odds':odd} for side,odd in (('HOME',2),('DRAW',3),('AWAY',4))]
        result=market_reference(quotes,quotes[0],.6,0)
        self.assertAlmostEqual(result['probability'],(.5)/(.5+1/3+.25))
        self.assertEqual(result['method'],'PROPORTIONAL_COMPLETE_BOOKMAKER_LINE');self.assertFalse(result['sharp_consensus'])
        quotes[-1]['bookmaker']='OTHER'
        self.assertEqual(market_reference(quotes,quotes[0],.6,0)['method'],'SINGLE_PRICE_BREAK_EVEN_PROXY')

    def test_integer_and_dnb_reference_condition_on_no_push(self):
        quote={**example(NOW)['quotes'][0],'line_id':'dnb','market':{'kind':'DNB','side':'HOME'},'odds':2.}
        other={**quote,'market':{'kind':'DNB','side':'AWAY'}}
        result=market_reference([quote,other],quote,.4,.2)
        self.assertAlmostEqual(result['model_probability'],.5);self.assertAlmostEqual(result['divergence'],0)
        self.assertTrue(result['conditional_on_no_push'])

    def test_duplicate_outcome_is_not_a_complete_reference(self):
        quote={**example(NOW)['quotes'][0],'line_id':'line'}
        result=market_reference([quote,dict(quote)],quote,.5,0)
        self.assertEqual(result['method'],'MISSING')

    def test_extreme_roma_paris_pattern_requires_recalculation_even_with_facts(self):
        p,case,q,context=controlled(win=.95,odds=2.)
        out=decision(p,case,q,context)
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['mode'],'UNKNOWN')
        self.assertIn('PROBABILITY_RECALCULATION_REQUIRED',out['limiting_factors'])
        self.assertIn('MODEL_MARKET_DIVERGENCE',[i['code'] for i in out['candidates'][0]['issues']])

    def test_prices_cannot_change_the_sealed_sports_probabilities(self):
        case=example(NOW);before=prepare(case['sports'],case['markets'],Policy())
        case['quotes'][0]['odds']=100.
        self.assertEqual(before,prepare(case['sports'],case['markets'],Policy()))

    def test_benfica_pattern_blocks_alternative_sharing_weakened_thesis(self):
        markets=[{'kind':'HANDICAP','side':'AWAY','line':1.5},{'kind':'BTTS','side':'YES'}]
        p,case,q,context=controlled(markets,.55,2.2)
        p['sports']['thesis_links']=[{'id':'away-can-score','markets':[c['key'] for c in p['candidates']],
                                     'premise_ids':['fact-tactics']}]
        opened={**q[0],'phase':'OPEN','odds':1.8,'observed_at':(NOW+timedelta(seconds=30)).isoformat(),
                'received_at':(NOW+timedelta(seconds=30)).isoformat()}
        out=decision(p,case,q+[opened],context)
        self.assertEqual(out['decision'],'PASS');self.assertTrue(out['thesis_reviews'])
        self.assertTrue(all('THESIS_REPLACEMENT_GUARD' in [i['code'] for i in c['issues']] for c in out['candidates']))

    def test_thesis_links_require_facts_and_predeclared_markets(self):
        case=example(NOW);case['sports']['thesis_links']=[{'id':'x','markets':['1X2:HOME','BTTS:YES'],'premise_ids':['nonexistent']}]
        with self.assertRaises(ValueError):prepare(case['sports'],case['markets'],Policy())

    def test_belgrano_matchup_inference_enters_unknown_not_confident_opposite(self):
        case=example(NOW);stamp=case['sports']['as_of']
        signal={'id':'matchup-conflict','key':'matchup_signal','value':{'status':'CONFLICT'},'kind':'INFERENCE','source_id':'statistics',
                'published_at':stamp,'received_at':stamp,'observed_at':stamp,'critical':True,'supports':['fact-tactics']}
        case['sports']['evidence'].append(signal)
        p=prepare(case['sports'],case['markets'],Policy());self.assertEqual(p['mode'],'UNKNOWN')
        self.assertIn('MODEL_MATCHUP_CONFLICT',[i['code'] for i in p['issues']])
        signal['kind']='FACT'
        with self.assertRaises(ValueError):prepare(case['sports'],case['markets'],Policy())

    def test_whyteleafe_coach_novelty_still_blocks(self):
        case=example(NOW)
        for e in case['sports']['evidence']:
            if e['key']=='coach':e['value']='NEW_COACH'
        p=prepare(case['sports'],case['markets'],Policy());self.assertEqual(p['mode'],'UNKNOWN')
        self.assertIn('UNKNOWN_CONTEXT',[i['code'] for i in p['issues']])

    def test_final_recheck_novel_context_cannot_keep_prior_bet_permission(self):
        p,case,q,context=controlled()
        self.assertEqual(decision(p,case,q,context)['decision'],'BET')
        stamp=case['recheck']['checked_at']
        fact={**case['recheck']['evidence'][0],'id':'late-novelty','key':'novelty','value':['UNFAMILIAR_CONTEXT'],
              'observed_at':stamp,'published_at':stamp,'received_at':stamp}
        case['recheck']['evidence'].append(fact)
        out=decision(p,case,q,context)
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['mode'],'UNKNOWN')
        self.assertIn('UNKNOWN_CONTEXT',out['limiting_factors']);self.assertEqual(out['risk']['stake'],0.)

    def test_final_recheck_matchup_conflict_enters_unknown(self):
        p,case,q,context=controlled();stamp=case['recheck']['checked_at']
        case['recheck']['evidence'].append({'id':'late-matchup','key':'matchup_signal','value':{'status':'CONFLICT'},
            'kind':'INFERENCE','source_id':'statistics','observed_at':stamp,'published_at':stamp,'received_at':stamp,
            'critical':True,'supports':[next(e['id'] for e in case['recheck']['evidence'] if e['key']=='tactics')]})
        out=decision(p,case,q,context)
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['mode'],'UNKNOWN')
        self.assertIn('MODEL_MATCHUP_CONFLICT',out['limiting_factors'])

    def test_protected_integer_lines_settle_push_exactly(self):
        self.assertEqual(settle(market_of({'kind':'HANDICAP','side':'AWAY','line':1}),2,1),'PUSH')
        self.assertEqual(settle(market_of({'kind':'TEAM_TOTAL','side':'AWAY_UNDER','line':2}),2,2),'PUSH')


class NewPostmatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.repo=Repository(Path(self.temp.name)/'test.sqlite')
        self.case=example(NOW);self.clock=[NOW];self.service=Service(self.repo,clock=lambda:self.clock[0])
        self.p=self.service.capture(self.case['sports'],self.case['markets'])
        self.clock[0]=time(self.case['decision_at'])
        self.d=self.service.decide(self.p['id'],self.case['quotes'],self.case['recheck'],{'bankroll':1000.,'peak':1000.},self.case['decision_at'])
        self.clock[0]=time(self.case['result']['received_at']);self.service.result(self.case['result'])

    def tearDown(self):
        self.repo.close();self.temp.cleanup()

    def test_feedback_error_brier_and_audit_keep_unknown_quality(self):
        for r in self.repo.all('calibration_history'):
            self.assertAlmostEqual(sum(r['prediction_error']),0)
            self.assertAlmostEqual(r['brier'],sum(e*e for e in r['prediction_error'])/2)
            self.assertEqual(r['competition_profile'],'MEN')
        audit=self.repo.all('postmatch_reports')[0]
        self.assertEqual(audit['quality'],'UNDETERMINED');self.assertEqual(len(audit['candidates']),7)
        self.assertTrue(all(c['quality']=='UNDETERMINED' for c in audit['candidates']))
        self.assertTrue(self.service.replay(self.d['id'])['matches'])

    def test_causal_labels_cannot_be_inferred_without_review_evidence(self):
        review={'market':self.p['candidates'][0]['key'],'decision_quality':'UNDETERMINED','causes':['UNKNOWN'],
                'roles':{},'notes':'No causal claim','category':'MODEL_MISS'}
        with self.assertRaisesRegex(ValueError,'needs evidence'):self.service.postmortem(self.d['id'],review,self.clock[0].isoformat())
        review['category']='UNKNOWN'
        saved=self.service.postmortem(self.d['id'],review,self.clock[0].isoformat());self.assertEqual(saved['category'],'UNKNOWN')

    def test_premise_assessment_needs_known_premise_and_evidence(self):
        review={'market':self.p['candidates'][0]['key'],'decision_quality':'UNDETERMINED','causes':['UNKNOWN'],
                'roles':{},'notes':'review','premise_observations':[{'premise_id':'fact-tactics','status':'FAILED','evidence':[]}]}
        with self.assertRaisesRegex(ValueError,'needs evidence'):self.service.postmortem(self.d['id'],review,self.clock[0].isoformat())
        review['premise_observations'][0]['premise_id']='missing'
        with self.assertRaises(ValueError):self.service.postmortem(self.d['id'],review,self.clock[0].isoformat())

    def test_cannot_backdate_new_decision_after_result_but_replay_still_works(self):
        with self.assertRaisesRegex(ValueError,'after kickoff'):
            self.service.decide(self.p['id'],self.case['quotes'],self.case['recheck'],{'bankroll':1000.,'peak':1000.},self.case['decision_at'])
        self.assertTrue(self.service.replay(self.d['id'])['matches'])

    def test_recorded_execution_clv_is_distinct_from_decision_quote(self):
        self.clock[0]=time(self.case['decision_at'])
        entry={'id':'recorded-only','market':self.p['candidates'][0]['key'],'odds':2.2,'stake':5.,'bookmaker':'SYNTHETIC_BOOK','origin':'EXTERNAL'}
        self.service.execution(self.d['id'],entry,self.case['decision_at'])
        self.clock[0]=time(self.case['result']['received_at'])
        close={**self.case['quotes'][0],'phase':'CLOSE','odds':2.,'observed_at':(NOW+timedelta(minutes=110)).isoformat(),
               'received_at':(NOW+timedelta(minutes=111)).isoformat()}
        self.service.closing(self.d['match_id'],close)
        clv=self.service.report()['clv'];executed=next(c for c in clv if c['kind']=='RECORDED_EXECUTION')
        self.assertAlmostEqual(executed['clv'],.1);self.assertEqual(executed['origin'],'EXTERNAL')
        self.assertTrue(any(c['kind']=='DECISION_QUOTE_NOT_EXECUTION' for c in clv))

    def test_risk_cohorts_include_pass_candidates_without_calling_them_bad_decisions(self):
        cohorts=self.service.report()['risk_cohorts'];self.assertEqual(sum(c['n'] for c in cohorts),7)
        self.assertTrue(all(c['competition_profile']=='MEN' for c in cohorts))
        self.assertTrue(all('not execution P/L' in c['kind_of_record'] for c in cohorts))


class RetrospectiveAuditTests(unittest.TestCase):
    def data(self):return json.loads((ROOT/'examples/audit_cases_20260927_30.json').read_text(encoding='utf-8'))

    def test_all_four_audits_are_retrospective_and_not_calibration(self):
        data=self.data();out=audit_cases(data,Policy())
        self.assertEqual(out['cases'],49);self.assertEqual(out['source_documents'],4)
        self.assertEqual(sum(out['outcomes'].values()),49)
        self.assertFalse(out['holdout_eligible']);self.assertFalse(out['monetary_permission'])
        self.assertTrue(all(r['cause']=='UNKNOWN' and r['clv'] is None for r in out['rows']))
        self.assertEqual(out,audit_cases(copy.deepcopy(data),Policy()))

    def test_retrospective_dataset_cannot_claim_holdout_and_duplicates_fail(self):
        data=self.data();data['holdout_eligible']=True
        with self.assertRaises(ValueError):audit_cases(data,Policy())
        data=self.data();data['cases'].append(data['cases'][0])
        with self.assertRaises(ValueError):audit_cases(data,Policy())

    def test_cli_reports_without_creating_a_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'absent.sqlite'
            done=subprocess.run([sys.executable,str(ROOT/'sefirot.py'),'--db',str(db),'audit-regressions',
                                 str(ROOT/'examples/audit_cases_20260927_30.json')],capture_output=True,text=True)
            self.assertEqual(done.returncode,0,done.stderr);self.assertFalse(db.exists())
            self.assertEqual(json.loads(done.stdout)['cases'],49)


if __name__=='__main__':unittest.main()
