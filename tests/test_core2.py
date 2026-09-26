import copy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot import Policy,Repository,Service
from sefirot.contracts import time,digest,REASONS
from sefirot.engine import prepare,decide,code_hash
from sefirot.evidence import inspect
from sefirot.fixtures import example
from sefirot.markets import market_of,settle,complete_overround,DEFAULT_POOL
from sefirot.probability import distribution,ev_bounds,fit_calibrator,calibrate,wilson
from sefirot.feedback import brier,competence,compare_versions
from sefirot.risk import size_risk

NOW=datetime(2026,9,26,18,tzinfo=timezone.utc)

class IntegratedCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.repo=Repository(Path(self.temp.name)/'core.sqlite')
        self.clock=[NOW];self.policy=Policy();self.service=Service(self.repo,self.policy,lambda:self.clock[0]);self.case=example(NOW)
    def tearDown(self):self.repo.close();self.temp.cleanup()
    def capture(self):return self.service.capture(self.case['sports'],self.case['markets'])
    def decision(self,p):
        self.clock[0]=time(self.case['decision_at'])
        return self.service.decide(p['id'],self.case['quotes'],self.case['recheck'],{'bankroll':1000.,'peak':1000.},self.case['decision_at'])
    def result(self):
        self.clock[0]=time(self.case['result']['received_at']);return self.service.result(self.case['result'])
    def test_F1_no_prices_in_sports_contract(self):
        s=copy.deepcopy(self.case['sports']);s['odds']=[2,3,4]
        with self.assertRaises(ValueError):prepare(s,DEFAULT_POOL,self.policy)
    def test_F1_price_changes_do_not_change_sealed_probability(self):
        p=self.capture();a=self.decision(p);self.case['quotes'][0]['odds']=5.;b=self.decision(p)
        self.assertEqual(a['prediction_id'],b['prediction_id']);self.assertEqual(a['candidates'][0]['base'],b['candidates'][0]['base'])
        self.assertNotEqual(a['candidates'][0]['ev'],b['candidates'][0]['ev'])
    def test_F2_no_flag_can_authorize_synthetic_or_unvalidated(self):
        p=self.capture();d=self.decision(p)
        self.assertEqual(d['decision'],'PASS');self.assertEqual(d['risk']['stake'],0)
        self.assertTrue(all(not c['eligible'] for c in d['candidates']))
        self.assertFalse(d['execution_enabled'])
    def test_F3_future_evidence_rejected(self):
        self.case['sports']['evidence'][0]['received_at']=(NOW+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):self.capture()
    def test_F3_late_history_excluded(self):
        before=prepare(self.case['sports'],DEFAULT_POOL,self.policy)
        row=copy.deepcopy(self.case['sports']['history'][0]);row['id']='future';row['received_at']=(NOW+timedelta(days=1)).isoformat();row['home_goals']=20
        self.case['sports']['history'].append(row)
        after=prepare(self.case['sports'],DEFAULT_POOL,self.policy)
        self.assertEqual(before['model']['rates'],after['model']['rates']);self.assertIn('future',after['model']['excluded_history'])
    def test_F3_target_result_rejected(self):
        self.case['sports']['history'][0]['id']=self.case['sports']['match']['id']
        with self.assertRaises(ValueError):self.capture()
    def test_F3_late_capture_cannot_be_prospective(self):
        self.clock[0]=NOW+timedelta(days=1)
        with self.assertRaises(ValueError):self.capture()
        p=self.service.capture(self.case['sports'],DEFAULT_POOL,replay=True);self.assertFalse(p['captured_prematch'])
    def test_F5_full_decision_replay_and_immutability(self):
        p=self.capture();d=self.decision(p);self.result()
        self.assertTrue(self.service.replay(d['id'])['matches']);self.assertTrue(self.repo.verify())
        for table in ('predictions','decisions','results','audit_logs'):
            with self.assertRaises(sqlite3.IntegrityError):self.repo.db.execute(f'DELETE FROM {table}')
        stored=self.repo.get('predictions',p['id']);self.assertEqual(stored['sports'],self.case['sports'])
    def test_F6_changed_coach_unknown(self):
        next(e for e in self.case['sports']['evidence'] if e['key']=='coach')['value']='NEW'
        p=self.capture();self.assertEqual(p['mode'],'UNKNOWN');self.assertIn('UNKNOWN_CONTEXT',[i['code'] for i in p['issues']])
    def test_F7_critical_assumption_blocks(self):
        self.case['sports']['evidence'][3]['kind']='ASSUMPTION'
        p=self.capture();self.assertIn('CRITICAL_EVIDENCE_UNRELIABLE',[i['code'] for i in p['issues']])
    def test_F7_inference_support_cycle_rejected(self):
        e=self.case['sports']['evidence'][3];e['kind']='INFERENCE';e['supports']=[e['id']]
        with self.assertRaises(ValueError):self.capture()
    def test_P4_conflict_requires_evidence_not_average(self):
        other=copy.deepcopy(self.case['sports']['evidence'][3]);other['id']='conflicting';other['source_id']='statistics';other['value']='DIFFERENT'
        self.case['sports']['evidence'].append(other);p=self.capture()
        self.assertTrue(p['witness']['conflicts']);self.assertIn('UNRESOLVED_CONFLICT',[i['code'] for i in p['issues']])
    def test_P4_same_source_explicit_newer_update_resolves(self):
        e=self.case['sports']['evidence'][3];other=copy.deepcopy(e);other.update(id='update',value='LATEST',supersedes=[e['id']],received_at=self.case['sports']['as_of'])
        self.case['sports']['evidence'].append(other)
        p=self.capture();self.assertFalse(p['witness']['conflicts']);self.assertEqual(p['witness']['resolved'][e['key']]['value'],'LATEST')
    def test_P6_disabled_source_missing(self):
        self.case['sports']['sources'][0]['enabled']=False
        p=self.capture();self.assertIn('MISSING_LINEUP',[i['code'] for i in p['issues']])
    def test_P7_sports_change_requires_new_seal(self):
        p=self.capture();next(e for e in self.case['recheck']['evidence'] if e['key']=='lineup')['value']='NEW_LINEUP'
        d=self.decision(p);self.assertIn('SPORTS_CHANGED_RECALCULATE',d['limiting_factors'])
    def test_P7_stale_quote_even_if_received_now(self):
        p=self.capture();q=self.case['quotes'][0];q['observed_at']=(NOW-timedelta(minutes=10)).isoformat()
        d=self.decision(p);self.assertIn('PRICE_STALE',[i['code'] for i in d['candidates'][0]['issues']])
    def test_P7_closing_cannot_enter_admission(self):
        p=self.capture();self.case['quotes'][0]['phase']='CLOSE'
        with self.assertRaises(ValueError):self.decision(p)
    def test_P7_closing_received_after_kickoff_is_audit_only(self):
        p=self.capture();d=self.decision(p);self.result();q=copy.deepcopy(self.case['quotes'][0]);q['phase']='CLOSE';q['odds']=2.
        q['observed_at']=(NOW+timedelta(minutes=119)).isoformat();q['received_at']=self.case['result']['received_at']
        self.service.closing(d['match_id'],q);self.assertAlmostEqual(self.service.report()['clv'][0]['clv'],.05)
    def test_P8_feedback_idempotent_no_duplicate_metrics(self):
        p=self.capture();self.decision(p);self.assertEqual(self.result()['records'],7)
        self.assertTrue(self.result()['idempotent']);self.assertEqual(len(self.service.report()['performance']),7)
        changed=copy.deepcopy(self.case['result']);changed['home_goals']=5
        with self.assertRaises(ValueError):self.service.result(changed)
    def test_P9_outcome_does_not_define_quality(self):
        p=self.capture();d=self.decision(p);self.result()
        review={'market':p['candidates'][0]['key'],'decision_quality':'UNDETERMINED','causes':['UNKNOWN'],'roles':{},'notes':'one win cannot validate probability'}
        pm=self.service.postmortem(d['id'],review,self.clock[0].isoformat());self.assertEqual(pm['outcome'],'WIN');self.assertEqual(pm['decision_quality'],'UNDETERMINED')
    def test_P15_override_is_new_revision_not_mutation(self):
        p=self.capture();s=copy.deepcopy(self.case['sports']);self.clock[0]+=timedelta(seconds=1);s['as_of']=self.clock[0].isoformat()
        next(e for e in s['evidence'] if e['key']=='lineup')['value']='CORRECTED'
        with self.assertRaises(ValueError):self.service.capture(s,DEFAULT_POOL,parent=p['id'],reason='INTUITION')
        new=self.service.capture(s,DEFAULT_POOL,parent=p['id'],reason='WRONG_LINEUP')
        self.assertNotEqual(p['id'],new['id']);self.assertEqual(new['revision'],1);self.assertEqual(self.repo.get('predictions',p['id'])['sports'],self.case['sports'])
    def test_P15_revision_budget_and_unchanged_snapshot(self):
        p=self.capture()
        with self.assertRaises(ValueError):self.service.capture(self.case['sports'],DEFAULT_POOL,parent=p['id'],reason='DATA_ERROR')
    def test_N1_bounded_pool(self):
        with self.assertRaises(ValueError):self.service.capture(self.case['sports'],DEFAULT_POOL+[{'kind':'1X2','side':'DRAW'}])
    def test_D1_D2_live_rejected(self):
        for market in ({'kind':'EXPRESS','side':'HOME'},{'kind':'CARDS','side':'OVER'}):
            with self.assertRaises(ValueError):self.service.capture(self.case['sports'],[market])
        self.case['sports']['match']['format']='LIVE';p=self.capture();self.assertIn('UNSUPPORTED_FORMAT',[i['code'] for i in p['issues']])
    def test_external_execution_audited_and_settled(self):
        p=self.capture();d=self.decision(p)
        entry={'id':'external-1','market':p['candidates'][0]['key'],'odds':2.1,'stake':10.,'bookmaker':'SYNTHETIC_BOOK','origin':'EXTERNAL'}
        e=self.service.execution(d['id'],entry,self.case['decision_at']);self.assertIn('EXECUTED_AGAINST_PASS',e['flags'])
        self.result();self.assertAlmostEqual(self.service.accounting()['pnl'],11.)
    def test_system_execution_cannot_override_pass(self):
        p=self.capture();d=self.decision(p);entry={'id':'bad','market':p['candidates'][0]['key'],'odds':2.1,'stake':10.,'bookmaker':'SYNTHETIC_BOOK','origin':'SYSTEM_RECOMMENDATION'}
        with self.assertRaises(ValueError):self.service.execution(d['id'],entry,self.case['decision_at'])
    def test_VOID_refunds_and_excludes_probability_score(self):
        p=self.capture();d=self.decision(p);self.case['result'].update(status='VOID',home_goals=None,away_goals=None)
        self.assertEqual(self.result()['records'],0);self.assertEqual(self.service.report()['performance'],[])
    def test_F3_split_cannot_be_relabelled(self):
        self.service.reserve(['x'],'CALIBRATION',self.clock[0].isoformat())
        with self.assertRaises(ValueError):self.service.reserve(['x'],'HOLDOUT',self.clock[0].isoformat())
        self.capture()
        with self.assertRaises(ValueError):self.service.reserve(['synthetic-001'],'HOLDOUT',self.clock[0].isoformat())

class NumericalTests(unittest.TestCase):
    def test_market_all_main_settlements(self):
        cases=[({'kind':'1X2','side':'DRAW'},1,1,'WIN'),({'kind':'DNB','side':'HOME'},1,1,'PUSH'),
               ({'kind':'HANDICAP','side':'AWAY','line':1},2,1,'PUSH'),({'kind':'TOTAL','side':'UNDER','line':3},2,1,'PUSH'),
               ({'kind':'TEAM_TOTAL','side':'AWAY_UNDER','line':1.5},2,1,'WIN'),({'kind':'BTTS','side':'NO'},2,0,'WIN'),
               ({'kind':'DOUBLE_CHANCE','side':'12'},2,2,'LOSS')]
        for m,h,a,want in cases:self.assertEqual(settle(market_of(m),h,a),want)
    def test_poisson_normalization_and_tail(self):
        for rates in ((.05,.05),(2.,1.),(12.,12.)):
            dist,tail=distribution(*rates);self.assertAlmostEqual(sum(dist.values()),1.);self.assertGreaterEqual(tail,0)
    def test_robust_ev_simplex_includes_push(self):
        lo,hi=ev_bounds([.5,.1,.2],[.7,.2,.4],2)
        self.assertAlmostEqual(lo,.1);self.assertAlmostEqual(hi,.5)
        with self.assertRaises(ValueError):ev_bounds([.7,.7,0],[.8,.8,.1],2)
    def test_wilson_endpoints(self):
        self.assertEqual(wilson(0,100)[0],0.)
        self.assertAlmostEqual(wilson(100,100)[1],1.)
        self.assertGreater(wilson(50,10_000)[0],0)
    def test_brier_known_answers(self):
        self.assertEqual(brier([1.,0.,0.],'WIN'),0)
        self.assertEqual(brier([1.,0.,0.],'LOSS'),1)
        self.assertAlmostEqual(brier([.5,0,.5],'WIN'),.25)
    def test_margin_requires_complete_same_book_line(self):
        base={'market':{'kind':'1X2','side':'HOME'},'bookmaker':'B','odds':2.,'observed_at':NOW.isoformat(),'line_id':'l','phase':'FINAL'}
        self.assertEqual(complete_overround([base]),[])
        rows=[{**base,'market':{'kind':'1X2','side':s},'odds':o} for s,o in [('HOME',2),('DRAW',3),('AWAY',6)]]
        self.assertAlmostEqual(complete_overround(rows)[0]['overround'],0)
    def test_calibrator_validation(self):
        records=[{'match_id':str(i),'market':'1X2:HOME','kind':'1X2','raw_win':.5,'outcome':'WIN' if i%2 else 'LOSS','received_at':NOW.isoformat(),'synthetic':True} for i in range(40)]
        a=fit_calibrator(records,'model','policy',NOW.isoformat());c=calibrate('1X2',[.5,0,.5],a,Policy())
        self.assertEqual(c['status'],'CALIBRATED_BIN');self.assertAlmostEqual(sum(c['base']),1.)
        self.assertLess(c['low'][0],.5);self.assertGreater(c['high'][0],.5)
        with self.assertRaises(ValueError):fit_calibrator(records+records,'m','p',NOW.isoformat())

class RiskAndGovernanceTests(unittest.TestCase):
    def risk(self,**overrides):
        args={'win':.7,'push':0.,'odds':2.,'bankroll':1000.,'peak':1000.,'quality':1.,'exposures':[],
              'match':{'id':'m','home':'A','away':'B','league':'L'},'model':'v1','scenario':'base','factors':[],
              'at':NOW.isoformat(),'policy':Policy()};args.update(overrides);return size_risk(**args)
    def test_risk_no_doubling_and_drawdown(self):
        normal=self.risk();self.assertGreater(normal['stake'],0);self.assertLessEqual(normal['stake'],5)
        self.assertLessEqual(self.risk(bankroll=900.)['stake'],normal['stake']);self.assertEqual(self.risk(bankroll=700.)['stake'],0)
    def test_correlation_by_event_and_model_caps(self):
        exposure={'stake':5.,'at':NOW.isoformat(),'groups':['match:m','model:v1']}
        self.assertEqual(self.risk(exposures=[exposure])['stake'],0)
        exposure={'stake':15.,'at':NOW.isoformat(),'groups':['model:v1']}
        self.assertEqual(self.risk(exposures=[exposure])['stake'],0)
    def test_daily_limit_counts_settled_turnover(self):
        exposure={'stake':20.,'at':NOW.isoformat(),'settled_at':NOW.isoformat(),'groups':[]}
        self.assertEqual(self.risk(exposures=[exposure])['stake'],0)
    def records(self,n,score=.9):
        return [{'match_id':str(i),'market':'1X2:HOME','model_id':'v','received_at':NOW.isoformat(),'brier':score,'baseline_brier':.25,'probabilities':[.5,0,.5],'outcome':'WIN'} for i in range(n)]
    def test_degradation_freeze_and_no_automatic_recovery(self):
        self.assertEqual(competence(self.records(29),Policy())['state'],'UNKNOWN')
        self.assertEqual(competence(self.records(30),Policy())['state'],'WEAK')
        self.assertEqual(competence(self.records(60),Policy())['state'],'FROZEN')
        self.assertEqual(competence(self.records(60,.1),Policy(),previous='FROZEN')['state'],'FROZEN')
    def test_critical_errors_cannot_hide_behind_good_score(self):
        self.assertEqual(competence(self.records(60,.01),Policy(),severe=2)['state'],'FROZEN')
    def test_paired_comparison_same_cases(self):
        old=self.records(60,.1);new=self.records(60,.3)
        self.assertEqual(compare_versions(old,new,Policy())['recommendation'],'ROLLBACK')
        new[0]['outcome']='LOSS'
        with self.assertRaises(ValueError):compare_versions(old,new,Policy())


class AdmissionTests(unittest.TestCase):
    """Controlled arbiter fixtures prove BET/conditional/PASS branches, not model quality."""
    def setup_case(self):
        case=example(NOW);case['sports']['synthetic']=False
        p=prepare(case['sports'],[DEFAULT_POOL[0]],Policy());p['sealed_at']=NOW.isoformat();p['model_id']='controlled-test-model'
        c=p['candidates'][0];c.update(base=[.8,0.,.2],low=[.75,0.,.15],high=[.85,0.,.25],calibration='CALIBRATED_BIN',calibration_n=500,stress_probabilities=[[.78,0,.22]])
        context={'journal_ok':True,'health':{c['key']:{'state':'WORKING','trust':'HIGH'}},'releases':{c['key']:{'passed':True}},'policy_approved':True,'captured_prematch':True,'exposures':[], 'sephirot_ratings':{c['key']:{role:{'trust':'HIGH'} for role in ('witness','probability','opponent')}}}
        quotes=[copy.deepcopy(case['quotes'][0])];quotes[0]['odds']=1.5
        # Independent corroboration is needed for a surprising discrepancy.
        extra=[]
        for e in case['recheck']['evidence']:
            if e['key'] in ('lineup','injuries','tactics'):extra.append({**e,'id':e['id']+'-independent','source_id':'statistics'})
        case['recheck']['evidence']+=extra
        return p,case,quotes,context
    def run_case(self,p,c,q,context):
        return decide(p,q,c['recheck'],c['decision_at'],context,{'bankroll':1000.,'peak':1000.},Policy())
    def test_actual_BET_branch_requires_all_gates(self):
        p,c,q,context=self.setup_case();d=self.run_case(p,c,q,context)
        self.assertEqual(d['decision'],'BET');self.assertEqual(d['verdict'],'playable');self.assertGreater(d['risk']['stake'],0)
    def test_each_critical_veto_overrides_high_rating(self):
        for field in ('journal_ok','policy_approved','captured_prematch'):
            p,c,q,context=self.setup_case();context[field]=False
            self.assertEqual(self.run_case(p,c,q,context)['decision'],'PASS')
        p,c,q,context=self.setup_case();context['health'][p['candidates'][0]['key']]['state']='FROZEN'
        self.assertEqual(self.run_case(p,c,q,context)['decision'],'PASS')
    def test_conditional_means_lower_risk_not_critical_override(self):
        from sefirot.contracts import finding
        p,c,q,context=self.setup_case();normal=self.run_case(p,c,q,context)
        p['issues'].append(finding('witness','OPTIONAL_SOURCE_UNAVAILABLE','WARN'))
        d=self.run_case(p,c,q,context);self.assertEqual(d['verdict'],'playable with conditions');self.assertLess(d['risk']['stake'],normal['risk']['stake'])
    def test_divergence_without_independent_corroboration_blocks(self):
        p,c,q,context=self.setup_case();c['recheck']['evidence']=[e for e in c['recheck']['evidence'] if e['source_id']=='official']
        d=self.run_case(p,c,q,context);self.assertEqual(d['decision'],'PASS');self.assertIn('DIVERGENCE_NEEDS_CORROBORATION',[i['code'] for i in d['candidates'][0]['issues']])
    def test_ordinary_loss_branch_not_automatic_veto(self):
        p,c,q,context=self.setup_case();self.assertTrue(p['candidates'][0]['counterexamples'])
        self.assertEqual(self.run_case(p,c,q,context)['decision'],'BET')

class CalibrationFlowTests(unittest.TestCase):
    def test_real_fit_holdout_feedback_flow_synthetic_cannot_certify(self):
        with tempfile.TemporaryDirectory() as temp:
            repo=Repository(Path(temp)/'calibration.sqlite');clock=[NOW-timedelta(days=30)]
            policy=replace(Policy(),min_calibration=2,min_context=2,min_holdout=4,health_window=2)
            svc=Service(repo,policy,lambda:clock[0])
            ids=[f'cal-{i}' for i in range(4)]+[f'test-{i}' for i in range(4)]
            svc.reserve(ids[:4],'CALIBRATION',clock[0].isoformat());svc.reserve(ids[4:],'HOLDOUT',clock[0].isoformat())
            artifact=None;last=None
            for i,mid in enumerate(ids):
                clock[0]=NOW-timedelta(days=20-i);case=example(clock[0],mid)
                if i==4:artifact=svc.calibrate(clock[0].isoformat());clock[0]+=timedelta(minutes=3);case=example(clock[0],mid)
                p=svc.capture(case['sports'],[DEFAULT_POOL[0]],artifact['hash'] if artifact else None)
                clock[0]=time(case['result']['received_at']);svc.result(case['result']);last=p
            reports=svc.validate(last['model_id'],clock[0].isoformat())
            self.assertEqual(len(reports),1);self.assertEqual(reports[0]['n'],4)
            self.assertFalse(reports[0]['passed']);self.assertIn('SYNTHETIC_NOT_PROOF',reports[0]['reasons']);self.assertTrue(repo.verify())
            repo.close()

class BacktestAndBoundaryTests(unittest.TestCase):
    def test_walk_forward_records_PASS_and_all_market_outcomes(self):
        from sefirot.backtesting import walk_forward
        cases=[example(NOW+timedelta(days=i),f'b{i}') for i in range(3)]
        report=walk_forward(cases)
        self.assertEqual(report['fixtures'],3);self.assertEqual(report['PASS'],3);self.assertEqual(report['metrics']['n'],21)
        self.assertFalse(report['can_certify_release'])
        with self.assertRaises(ValueError):walk_forward(cases+[cases[0]])
    def test_negative_nan_inf_and_quarter_lines_rejected(self):
        from sefirot._payoffs import implied,payoff_ev,fair_odds
        for value in (True,float('nan'),float('inf'),1.,-3.):
            with self.assertRaises(ValueError):implied(value)
        for fn in (lambda:payoff_ev(.8,.3,2),lambda:fair_odds(0,0),lambda:market_of({'kind':'TOTAL','side':'OVER','line':2.25}),lambda:Policy(max_candidates=8)):
            with self.assertRaises(ValueError):fn()
    def test_timezone_equivalent_quote_order_is_valid(self):
        from sefirot.markets import validate_quote
        q=copy.deepcopy(example(NOW)['quotes'][0]);q['observed_at']='2026-09-26T21:01:00+03:00';q['received_at']='2026-09-26T18:01:00Z'
        self.assertEqual(validate_quote(q,'2026-09-26T20:00:00Z','2026-09-26T18:02:00Z','2026-09-26T18:00:00Z').kind,'1X2')
    def test_empty_history_unknown_and_missing_calibration_bounds(self):
        case=example(NOW);case['sports']['history']=[];p=prepare(case['sports'],DEFAULT_POOL,Policy())
        self.assertEqual(p['mode'],'UNKNOWN');self.assertEqual(p['candidates'][0]['low'],[0,0,0]);self.assertEqual(p['candidates'][0]['high'],[1,1,1])
    def test_calibration_temporal_leakage_and_hash_rejected(self):
        case=example(NOW)
        records=[{'match_id':'seen','market':'1X2:HOME','kind':'1X2','raw_win':.5,'outcome':'WIN','received_at':NOW.isoformat(),'synthetic':True}]
        a=fit_calibrator(records,code_hash(),Policy().fingerprint,NOW.isoformat())
        with self.assertRaises(ValueError):prepare(case['sports'],DEFAULT_POOL,Policy(),a)
        a['fit_at']=(NOW-timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):prepare(case['sports'],DEFAULT_POOL,Policy(),a)
    def test_empty_backtest_honest_no_quality_claim(self):
        from sefirot.backtesting import walk_forward
        report=walk_forward([]);self.assertEqual(report['metrics']['n'],0);self.assertIsNone(report['metrics']['brier'])

class LedgerAdversarialTests(unittest.TestCase):
    setUp=IntegratedCase.setUp
    tearDown=IntegratedCase.tearDown
    capture=IntegratedCase.capture
    decision=IntegratedCase.decision
    result=IntegratedCase.result
    def test_market_shopping_existing_match_rejected(self):
        p=self.capture();changed=copy.deepcopy(DEFAULT_POOL);changed[0]['side']='AWAY'
        with self.assertRaises(ValueError):self.service.capture(self.case['sports'],changed)
    def test_source_data_cannot_be_changed_without_revision(self):
        p=self.capture();self.clock[0]+=timedelta(seconds=1)
        self.case['sports']['as_of']=self.clock[0].isoformat()
        with self.assertRaises(ValueError):self.capture()
    def test_future_result_operation_rejected(self):
        self.capture()
        with self.assertRaises(ValueError):self.service.result(self.case['result'])
    def test_result_transaction_has_automatic_postmatch_audit(self):
        p=self.capture();d=self.decision(p);self.result()
        audits=self.repo.all('postmatch_reports');self.assertEqual(len(audits),1);self.assertEqual(audits[0]['quality'],'UNDETERMINED')
    def test_no_certified_version_activation(self):
        p=self.capture()
        with self.assertRaises(ValueError):self.service.activate(p['model_id'],self.clock[0].isoformat())
    def test_recovery_cannot_skip_fresh_validation(self):
        with self.assertRaises(ValueError):self.service.recover('unknown','fix','nonexistent',self.clock[0].isoformat())
    def test_tampered_payload_is_detected_even_if_sql_trigger_removed(self):
        p=self.capture();self.repo.db.execute('DROP TRIGGER predictions_no_update')
        self.repo.db.execute("UPDATE predictions SET payload='{}' WHERE id=?",(p['id'],))
        self.assertFalse(self.repo.verify())
    def test_external_execution_retry_is_idempotent(self):
        p=self.capture();d=self.decision(p);entry={'id':'retry','market':p['candidates'][0]['key'],'odds':2.1,'stake':10.,'bookmaker':'SYNTHETIC_BOOK','origin':'EXTERNAL'}
        first=self.service.execution(d['id'],entry,self.case['decision_at']);second=self.service.execution(d['id'],entry,self.case['decision_at'])
        self.assertEqual(first,second);self.assertEqual(len(self.repo.all('bets')),1)


class WorkerTests(unittest.TestCase):
    def test_inbox_processes_once_and_rejects_mutation(self):
        from sefirot.worker import process_inbox
        with tempfile.TemporaryDirectory() as temp:
            repo=Repository(Path(temp)/'app.sqlite');svc=Service(repo,clock=lambda:NOW);case=example(NOW)
            inbox=Path(temp)/'inbox';inbox.mkdir();path=inbox/'001.json'
            job={'id':'capture1','type':'CAPTURE','payload':{'sports':case['sports'],'markets':case['markets']}}
            path.write_text(json.dumps(job));self.assertEqual(process_inbox(svc,inbox)[0]['status'],'DONE')
            self.assertEqual(process_inbox(svc,inbox)[0]['status'],'ALREADY_PROCESSED')
            job['payload']['sports']['match']['id']='different';path.write_text(json.dumps(job))
            self.assertEqual(process_inbox(svc,inbox)[0]['status'],'ERROR');repo.close()

if __name__=='__main__':unittest.main()
