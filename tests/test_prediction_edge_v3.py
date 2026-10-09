import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import Policy, digest
from sefirot.fixtures import example
from sefirot.markets import Market, payoff_ev
from sefirot.probability import estimate
from research.prediction_edge_v3.models import Config, MODELS, baseline, fit, predict, score_mass, tau
from research.prediction_edge_v3.benchmark import CONTRACTS, evaluate as _evaluate, project, proper_scores, paired_interval, validate_manifest
from research.prediction_edge_v3.market import compare_1x2, builder, clv
from research.prediction_edge_v3.arena import ablation

NOW=datetime(2026,10,9,tzinfo=timezone.utc)

def history():
    out=[]
    for i in range(84):
        start=NOW-timedelta(days=90-i)
        out.append(dict(id=str(i),home='ABCD'[i%4],away='ABCD'[(i%4+1+(i//4)%3)%4],
                        league='L',competition_profile='MEN',season=2026,kickoff=start.isoformat(),
                        finished_at=(start+timedelta(hours=2)).isoformat(),received_at=(start+timedelta(hours=3)).isoformat(),
                        home_goals=(i*7)%4,away_goals=(i*3)%3,source_id='synthetic',receipt_sha='a'*64,synthetic=True))
    return out

def fitting(model='DC_DYNAMIC_V1', rows=None, config=Config()):
    return fit(model,history() if rows is None else rows,cutoff=NOW.isoformat(),league='L',profile='MEN',season=2026,config=config)

def predicting(a, **kw):
    return predict(a,**(dict(match_id='future',home='A',away='B',league='L',profile='MEN',season=2026,
                            as_of=NOW.isoformat(),kickoff=(NOW+timedelta(days=1)).isoformat())|kw))

def evaluate(m,f,r):
    return _evaluate(m,f,r,as_of=(NOW+timedelta(days=1)).isoformat())

def experiment():
    m=dict(schema='edge-v3-manifest-v1',registered_at=NOW.isoformat(),training_ids=['train'],calibration_ids=['cal'],viewed_test_ids=['old'],
           members=[dict(id='f',kickoff=(NOW+timedelta(hours=4)).isoformat(),league='L',profile='MEN')],models=list(MODELS),contracts=list(CONTRACTS),
           primary='1X2:raw:log_loss',research_hash='research',policy_hash='policy')
    p=project(score_mass(1.4,1.1)[0])
    f=dict(fixture_id='f',sealed_at=(NOW+timedelta(hours=1)).isoformat(),manifest_hash=digest(m),research_hash='research',policy_hash='policy',
           models={model:dict(raw=copy.deepcopy(p),calibrated=None) for model in MODELS},synthetic=True)
    f['hash']=digest(f)
    r=dict(fixture_id='f',finished_at=(NOW+timedelta(hours=6)).isoformat(),received_at=(NOW+timedelta(hours=7)).isoformat(),goals=[1,0],status='FT',receipt_sha='a'*64)
    return m,f,r

class ModelTests(unittest.TestCase):
    def test_baseline_exact_replay(self):
        s=example(NOW)['sports']; self.assertEqual(baseline(s,Policy()),estimate(s,Policy()))
    def test_zero_rate(self):
        m,t=score_mass(0,0); self.assertEqual(m[0,0],1); self.assertEqual(t,0)
    def test_extreme_rates(self):
        for a,b in [(12,12),(.01,12),(1.5,1.2)]:
            m,t=score_mass(a,b); self.assertAlmostEqual(sum(m.values()),1);self.assertLess(t,1e-12)
    def test_invalid_rates(self):
        for v in [-1,13,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError): score_mass(v,1)
    def test_dc_four_cells_and_marginals(self):
        raw,_=score_mass(1.5,1.1); m,_=score_mass(1.5,1.1,-.1)
        for cell in [(0,0),(0,1),(1,0),(1,1)]: self.assertAlmostEqual(m[cell]/raw[cell],tau(*cell,1.5,1.1,-.1))
        self.assertAlmostEqual(m[2,3],raw[2,3])
        self.assertAlmostEqual(sum(p for (h,a),p in m.items() if h==0),sum(p for (h,a),p in raw.items() if h==0))
    def test_invalid_rho(self):
        with self.assertRaises(ValueError): score_mass(12,12,.1)
    def test_both_models_fit_or_explicit_nonconvergence(self):
        for model in MODELS[1:]:
            a=fitting(model); self.assertEqual(a['status'],'FITTED_SHADOW')
            p=predicting(a); self.assertEqual(p['status'],'SHADOW_ONLY');self.assertAlmostEqual(sum(p['mass'].values()),1)
    def test_missing_history(self): self.assertEqual(fitting(rows=[])['status'],'UNTRAINABLE')
    def test_insufficient_team(self): self.assertEqual(predicting(fitting('SOS_LITE_V1'),home='NEW')['status'],'INSUFFICIENT_HISTORY')
    def test_duplicate_and_revision(self):
        rows=history();rows.append(dict(rows[0],home_goals=3))
        with self.assertRaises(ValueError):fitting(rows=rows)
    def test_future_receipt(self):
        rows=history();rows[0]['received_at']=(NOW+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):fitting(rows=rows)
    def test_future_kickoff(self):
        rows=history();rows[0]['kickoff']=(NOW+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):fitting(rows=rows)
    def test_mixed_context(self):
        for k,v in [('league','other'),('competition_profile','WOMEN'),('season',2023),('season',2027)]:
            rows=history();rows[0][k]=v
            with self.assertRaises(ValueError):fitting(rows=rows)
    def test_stale_history(self):
        with self.assertRaises(ValueError):fitting(config=Config(history_days=30))
    def test_odds_poisoning(self):
        rows=history();rows[0]['odds']=2
        with self.assertRaises(ValueError):fitting(rows=rows)
    def test_receipt_required(self):
        rows=history();rows[0]['receipt_sha']='fake'
        with self.assertRaises(ValueError):fitting(rows=rows)
    def test_artifact_tampering(self):
        a=fitting('SOS_LITE_V1');a['cutoff']='2020-01-01T00:00:00Z'
        with self.assertRaises(ValueError):predicting(a)
    def test_target_and_future_fit(self):
        a=fitting('SOS_LITE_V1')
        for kw in [dict(match_id='0'),dict(as_of=(NOW-timedelta(days=1)).isoformat()),dict(profile='WOMEN')]:
            with self.assertRaises(ValueError):predicting(a,**kw)
    def test_fit_expiry(self):
        self.assertEqual(predicting(fitting('SOS_LITE_V1'),as_of=(NOW+timedelta(days=8)).isoformat(),kickoff=(NOW+timedelta(days=9)).isoformat())['status'],'STALE_FIT')
    def test_nonconvergence_abstains(self):
        a=fitting(config=Config(iterations=1)); self.assertEqual(predicting(a)['status'],'UNTRAINABLE_NONCONVERGED')
    def test_history_order_invariant(self):
        self.assertEqual(fitting('SOS_LITE_V1'),fitting('SOS_LITE_V1',rows=list(reversed(history()))))
    def test_season_decay(self):
        from research.prediction_edge_v3.models import weight
        r=history()[0];q=dict(r,season=2025)
        self.assertAlmostEqual(weight(q,NOW.isoformat(),2026,Config())/weight(r,NOW.isoformat(),2026,Config()),.5)

class BenchmarkTests(unittest.TestCase):
    def test_common_mass_and_push(self):
        p=project({(1,1):1.});self.assertEqual(p['1X2'],[0,1,0]);self.assertEqual(p['DNB:HOME'],[0,1,0])
    def test_scores(self): self.assertEqual(proper_scores([1,0,0],0),dict(brier=0,log_loss=0))
    def test_wrong_simplex(self):
        with self.assertRaises(ValueError):proper_scores([.9,.9,0],0)
    def test_paired_comparison(self):
        m,f,r=experiment();s=evaluate(m,[f],[r]);self.assertFalse(s['proven_superiority']);self.assertTrue(s['synthetic'])
        self.assertEqual(s['scorecards'][0]['paired_delta']['log_loss']['mean'],0)
    def test_abstentions_in_denominator(self):
        m,f,r=experiment(); f['models']['SOS_LITE_V1']=None;f.pop('hash');f['hash']=digest(f)
        s=evaluate(m,[f],[r]);self.assertEqual(s['scorecards'][0]['paired_n'],0)
        self.assertEqual(s['scorecards'][2]['coverage'],0)
    def test_missing_calibration_not_raw(self):
        m,f,r=experiment();s=evaluate(m,[f],[r]);self.assertTrue(all(c['scored']==0 for c in s['scorecards'] if c['variant']=='calibrated'))
    def test_no_data_null(self):
        m,_,_=experiment();s=evaluate(m,[],[]);self.assertIsNone(s['scorecards'][0]['metrics']['brier'])
    def test_holdout_overlap(self):
        m,_,_=experiment();m['viewed_test_ids']=['f']
        with self.assertRaises(ValueError):validate_manifest(m)
    def test_retroactive_holdout(self):
        m,_,_=experiment();m['registered_at']=(NOW+timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):validate_manifest(m)
    def test_revised_result(self):
        m,f,r=experiment()
        with self.assertRaises(ValueError):evaluate(m,[f],[r,r])
    def test_duplicate_forecast(self):
        m,f,r=experiment()
        with self.assertRaises(ValueError):evaluate(m,[f,f],[r])
    def test_seal_mutation(self):
        m,f,r=experiment();f['models']['BASELINE_V1']['raw']['1X2']=[1,0,0]
        with self.assertRaises(ValueError):evaluate(m,[f],[r])
    def test_live_forecast(self):
        m,f,r=experiment();f['sealed_at']=r['finished_at'];f.pop('hash');f['hash']=digest(f)
        with self.assertRaises(ValueError):evaluate(m,[f],[r])
    def test_void_excluded(self):
        m,f,r=experiment();r.update(status='VOID',goals=None);s=evaluate(m,[f],[r]);self.assertEqual(s['void'],1);self.assertEqual(s['scorecards'][0]['scored'],0)
    def test_cluster_not_legs(self):
        self.assertIsNone(paired_interval([('day',1)]*7));self.assertEqual(paired_interval([('d1',.1),('d2',.1)]),[.1,.1])

class MarketTests(unittest.TestCase):
    def quotes(self):
        return [dict(fixture_id='f',bookmaker='B',line_id='l',side=s,odds=o,observed_at=NOW.isoformat(),received_at=NOW.isoformat(),rules='REGULATION_90',verified=True) for s,o in [('HOME',2.),('DRAW',3.),('AWAY',4.)]]
    def compare(self,quotes,**kw):
        return compare_1x2(**(dict(fixture_id='f',probabilities=[.5,.3,.2],lower_bounds=[.4,.2,.1],sealed_at=NOW.isoformat(),kickoff=(NOW+timedelta(hours=1)).isoformat(),at=NOW.isoformat(),quotes=quotes)|kw))
    def test_partition(self):
        r=self.compare(self.quotes());self.assertAlmostEqual(sum(r['reference']),1);self.assertAlmostEqual(r['reference'][0],6/13)
    def test_single_price_not_consensus(self):self.assertEqual(self.compare(self.quotes()[:1])['status'],'NO_DATA')
    def test_no_uncertainty_no_edge(self):self.assertEqual(self.compare(self.quotes(),lower_bounds=None)['status'],'NO_DATA')
    def test_quote_poisoning(self):
        for k,v in [('fixture_id','other'),('rules','EXTRA_TIME'),('verified',False),('odds',float('nan'))]:
            q=self.quotes();q[0][k]=v
            with self.assertRaises(ValueError):self.compare(q)
    def test_duplicate_quote(self):
        q=self.quotes()
        with self.assertRaises(ValueError):self.compare(q+[q[0]])
    def test_stale_quote(self):
        q=self.quotes();q[0]['observed_at']=(NOW-timedelta(minutes=3)).isoformat()
        with self.assertRaises(ValueError):self.compare(q)
    def test_push_ev(self):self.assertAlmostEqual(payoff_ev(.4,.3,2),.1)
    def test_builder_correlation(self):
        mass={(0,0):.5,(2,1):.5};r=builder([Market('BTTS','YES'),Market('TOTAL','OVER',2.5)],mass)
        self.assertEqual(r['joint_probability'],.5);self.assertIsNone(r['builder_ev'])
    def test_builder_contradiction(self):
        self.assertEqual(builder([Market('BTTS','YES'),Market('BTTS','NO')],score_mass(1,1)[0])['joint_probability'],0)
    def test_builder_push_rejected(self):
        with self.assertRaises(ValueError):builder([Market('DNB','HOME'),Market('BTTS','YES')],score_mass(1,1)[0])
    def test_clv(self):
        e=dict(fixture_id='f',bookmaker='B',contract='1X2:HOME',rules='REGULATION_90',verified=True,odds=2.2,observed_at=NOW.isoformat(),received_at=NOW.isoformat())
        c=dict(e,odds=2,observed_at=(NOW+timedelta(minutes=30)).isoformat(),received_at=(NOW+timedelta(minutes=30)).isoformat())
        self.assertAlmostEqual(clv(e,c,kickoff=(NOW+timedelta(hours=1)).isoformat())['raw_price_ratio'],.1)
    def test_arena_empty_no_benefit(self):
        m,_,_=experiment();r=ablation(m['members'],[],[str(i) for i in range(8)]);self.assertFalse(r['proven_benefit']);self.assertEqual(r['complete_records'],0)
    def test_arena_false_veto(self):
        m,f,r=experiment();roles=[str(i) for i in range(8)]
        row=dict(fixture_id='f',sealed_at=f['sealed_at'],reviewed_at=f['sealed_at'],result_received_at=r['received_at'],core=[.8,.1,.1],candidate=None,outcome=0,vetoes={role:role=='0' for role in roles})
        a=ablation(m['members'],[row],roles);self.assertEqual(a['roles']['0']['false_veto_fraction'],1);self.assertEqual(a['roles']['0']['without_role']['retained'],1)

class CalibrationTests(unittest.TestCase):
    def test_existing_per_contract_calibration_can_break_exclusivity(self):
        from sefirot.probability import bin_key, calibrate, CALIBRATION_SCHEMA
        home,away=Market('1X2','HOME'),Market('1X2','AWAY')
        artifact={'version':CALIBRATION_SCHEMA,'buckets':{bin_key(m,.4,'MEN'):[20,0,0] for m in (home,away)}}
        result=[calibrate(m,[.4,0,.6],artifact,Policy(),'MEN')['base'][0] for m in (home,away)]
        self.assertGreater(sum(result),1)
    def test_temperature_coherence(self):
        from research.prediction_edge_v3.calibration import transform
        mass=score_mass(1.4,1.1)[0]
        for t in (.8,1.,1.2):
            p=project(transform(mass,t))
            self.assertAlmostEqual(sum(p['1X2']),1)
            self.assertAlmostEqual(p['DOUBLE_CHANCE:1X'][0],sum(p['1X2'][:2]))
    def test_calibration_overlap(self):
        from research.prediction_edge_v3.calibration import fit_temperature
        with self.assertRaises(ValueError):
            fit_temperature([],calibration_ids=['x'],training_ids=['x'],holdout_ids=[],fit_at=NOW.isoformat(),model_hash='x')
    def test_calibration_insufficient(self):
        from research.prediction_edge_v3.calibration import fit_temperature
        a=fit_temperature([],calibration_ids=[],training_ids=[],holdout_ids=[],fit_at=NOW.isoformat(),model_hash='x')
        self.assertIsNone(a['temperature'])
    def test_calibration_fit_apply_and_leakage(self):
        from research.prediction_edge_v3.calibration import fit_temperature,apply_temperature
        rows=[dict(fixture_id=str(i),model_hash='m',sealed_at=(NOW-timedelta(days=2)).isoformat(),
                   kickoff=(NOW-timedelta(days=1)).isoformat(),finished_at=(NOW-timedelta(hours=20)).isoformat(),
                   received_at=(NOW-timedelta(hours=19)).isoformat(),mass={(0,0):.4,(1,0):.6},goals=[1,0],synthetic=True) for i in range(60)]
        a=fit_temperature(rows,calibration_ids=[str(i) for i in range(60)],training_ids=[],holdout_ids=['new'],fit_at=NOW.isoformat(),model_hash='m')
        self.assertEqual(a['status'],'FITTED_SHADOW')
        self.assertIsNotNone(apply_temperature(a,rows[0]['mass'],fixture_id='new',as_of=(NOW+timedelta(hours=1)).isoformat(),model_hash='m'))
        with self.assertRaises(ValueError):apply_temperature(a,rows[0]['mass'],fixture_id='0',as_of=(NOW+timedelta(hours=1)).isoformat(),model_hash='m')
    def test_result_after_evaluation(self):
        m,f,r=experiment()
        with self.assertRaises(ValueError):_evaluate(m,[f],[r],as_of=NOW.isoformat())

class FinalGuardTests(unittest.TestCase):
    def test_premature_history_result(self):
        rows=history();rows[0]['finished_at']=rows[0]['kickoff']
        with self.assertRaises(ValueError):fitting(rows=rows)
    def test_premature_benchmark_result(self):
        m,f,r=experiment();r['finished_at']=(NOW+timedelta(hours=4,minutes=10)).isoformat()
        with self.assertRaises(ValueError):evaluate(m,[f],[r])
    def test_unequal_coverage_has_explicit_paired_metrics(self):
        m,f,r=experiment();m['members'].append(dict(m['members'][0],id='g'))
        f['manifest_hash']=digest(m);f.pop('hash');f['hash']=digest(f)
        g=copy.deepcopy(f);g['fixture_id']='g';g['models']['SOS_LITE_V1']=None
        g['models']['DC_DYNAMIC_V1']['raw']['1X2']=[.9,.05,.05];g.pop('hash');g['hash']=digest(g)
        rg=dict(r,fixture_id='g',goals=[0,1]);s=evaluate(m,[f,g],[r,rg])
        row=s['scorecards'][1];self.assertEqual(row['scored'],2);self.assertEqual(row['paired_n'],1)
        self.assertNotEqual(row['metrics']['log_loss'],row['paired_metrics']['log_loss'])
    def test_manifest_partial_markets_rejected(self):
        m,_,_=experiment();m['contracts']=m['contracts'][:-1]
        with self.assertRaises(ValueError):validate_manifest(m)
    def test_extra_market_footprint_rejected(self):
        m,f,r=experiment();f['models']['BASELINE_V1']['raw']['EXTRA']=[1,0,0]
        f.pop('hash');f['hash']=digest(f)
        with self.assertRaises(ValueError):evaluate(m,[f],[r])
    def test_impossible_contract_push_rejected(self):
        m,f,r=experiment();f['models']['BASELINE_V1']['raw']['BTTS:YES']=[.4,.2,.4]
        f.pop('hash');f['hash']=digest(f)
        with self.assertRaises(ValueError):evaluate(m,[f],[r])

if __name__=='__main__':unittest.main()
