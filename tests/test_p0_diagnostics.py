import copy,json,math,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.evaluation import devig
from sefirot.diagnostics import bucket,jaccard,portfolio,drawdown,bootstrap_intervals,monte_carlo,verify_source,diagnostics
from sefirot.research import elo_predictions
class ShinTests(unittest.TestCase):
 def test_external_reference(self):
  # mberk/shin README, retrieved 2026-09-27.
  for a,b in zip(devig([2.6,2.4,4.3],'shin'),[.37299406033208965,.4047794109200184,.2222265287474275]):self.assertAlmostEqual(a,b,places=10)
 def test_fair_symmetric_extreme_permutations(self):
  for odds in ([3.,3.,3.],[2.,2.,2.],[1.01,100.,200.],[1.1,10.,20.],[2.1,3.5,4.]):
   p=devig(odds,'shin');self.assertAlmostEqual(sum(p),1,places=11);self.assertTrue(all(0<=v<=1 for v in p))
   for a,b in zip(p,reversed(devig(list(reversed(odds)),'shin'))):self.assertAlmostEqual(a,b,places=11)
 def test_rejects_invalid(self):
  for odds in ([4.,4.,4.],[1.,3.,4.],[True,3.,4.],[2.,3.],[math.nan,3.,4.],[math.inf,3.,4.]):
   with self.subTest(odds=odds),self.assertRaises(ValueError):devig(odds,'shin')
 def test_cash_ev_independent(self):
  p=[.5,.3,.2];odds=[2.1,3.5,4.];selections=[]
  for method in ('shin','power','proportional'):
   devig(odds,method);selections.append(max(range(3),key=lambda i:p[i]*odds[i]-1))
  self.assertEqual(selections,[0,0,0])
class DiagnosticTests(unittest.TestCase):
 def test_boundaries_and_empty_jaccard(self):
  self.assertEqual([bucket(x,[1.5,1.8,2.2,3.]) for x in (1.49,1.5,1.8,2.2,3.)],[0,1,2,3,4]);self.assertEqual(bucket(-.01,[0,.02,.05,.1]),0)
  self.assertEqual(jaccard({1,2},{2,3}),1/3);self.assertIsNone(jaccard(set(),set()))
 def test_empty_portfolio(self):
  p=portfolio([]);self.assertIsNone(p['yield']);self.assertIsNone(p['clv']['mean']);self.assertEqual(p['n'],0)
 def test_hand_portfolio(self):
  bets=[{'date':'2024-01-01','pnl':2.,'won':True,'odds':3.,'p_model':.4,'ev':.2,'odds_clv':.1},{'date':'2024-01-02','pnl':-1.,'won':False,'odds':2.,'p_model':.6,'ev':.2,'odds_clv':None}]
  p=portfolio(bets);self.assertEqual(p['pnl'],1);self.assertEqual(p['yield'],.5);self.assertEqual(p['max_drawdown'],1);self.assertEqual(p['clv_missing'],1);self.assertEqual(p['positive_clv_fraction'],1)
 def test_drawdown_initial_zero(self):self.assertEqual(drawdown([-1,-1,3,-2]),2)
 def test_trace_does_not_change_predictions_or_leak(self):
  rows=[{'id':str(i),'date':f'2024-08-{i//2+1:02d}','season':2024,'home':'A','away':'B','y':i%3} for i in range(6)]
  t={};p=elo_predictions(rows,legacy=True,trace=t);self.assertEqual(p,elo_predictions(rows,legacy=True))
  altered=copy.deepcopy(rows);altered[-1]['y']=0;u={};q=elo_predictions(altered,legacy=True,trace=u)
  self.assertEqual(p,q);self.assertEqual(t,u);self.assertEqual(t['0']['season_counts'],[0,0]);self.assertEqual(t['2']['season_counts'],[2,2])
  reverse=rows[:];reverse[0:2]=reversed(reverse[:2]);self.assertEqual(p,elo_predictions(reverse,legacy=True))
 def test_bootstrap_pairing_seed(self):
  records=[{'date':'2024-01-01','y':0,'davidson':[.5,.3,.2],'elo':[.5,.3,.2],'market':[.5,.3,.2]}];cfg={'bootstrap_seed':1,'block_days':14,'bootstrap_repetitions':30}
  a=bootstrap_intervals(records,[],cfg);self.assertEqual(a,bootstrap_intervals(records,[],cfg));self.assertEqual(a['brier_vs_elo']['low'],0);self.assertIsNone(a['yield']['low'])
 def test_monte_carlo_degenerate(self):
  r=monte_carlo([{'odds':2.,'p_model':1.,'pnl':1.}],{'monte_carlo_seed':2,'monte_carlo_repetitions':20},'p_model');self.assertEqual(r['simulated']['mean'],1);self.assertEqual(r['percentile_le_observed'],1)
 def test_hash_mismatch(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.json';p.write_text('{}')
   with self.assertRaisesRegex(ValueError,'hash mismatch'):verify_source([],p,{'source_report_sha256':'wrong'})
 def test_exclusive_output(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaisesRegex(ValueError,'already exists'):diagnostics([],None,None,d)

class P0IntegrationTests(unittest.TestCase):
 def setUp(self):
  from test_research import ResearchTests
  ResearchTests.setUp(self)
 def tearDown(self):self.temp.cleanup()
 def test_replay_reproducibility_cohort_totals_and_missing_closing(self):
  import hashlib
  from sefirot.research import benchmark
  source=self.root/'source.json';original=benchmark(self.paths,source)
  cfg=json.loads((Path(__file__).resolve().parents[1]/'config/p0_diagnostic_design.json').read_text())
  cfg.update(source_report_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),source_run_id=original['run_id'],dataset_hash=original['dataset']['dataset_hash'],bootstrap_repetitions=20,monte_carlo_repetitions=20)
  design=self.root/'design.json';design.write_text(json.dumps(cfg))
  a=diagnostics(self.paths,source,design,self.root/'a');b=diagnostics(self.paths,source,design,self.root/'b')
  self.assertEqual(a,b)
  r=a['P0_COHORT_ANALYSIS'];self.assertEqual(r['original_portfolio']['n'],original['simulation']['n'])
  self.assertEqual(r['original_portfolio']['clv_missing'],r['original_portfolio']['n'])
  for axis,groups in r['cohorts'].items():
   self.assertEqual(sum(v['n'] for v in groups.values()),r['original_portfolio']['n'])
   self.assertAlmostEqual(sum(v['pnl'] for v in groups.values()),r['original_portfolio']['pnl'])
  self.assertFalse(r['monetary_permission']);self.assertEqual(a['P0_DEVIG_SENSITIVITY']['cash_selection_jaccard'],1)
  self.assertEqual(r['monte_carlo']['p_close']['n'],0)
 def test_price_and_closing_cannot_change_sports_trace(self):
  from sefirot.research import load_csvs
  rows,_=load_csvs(self.paths);t={};before=elo_predictions(rows,trace=t)
  altered=copy.deepcopy(rows)
  for r in altered:r['prices']={'B365':[500,1.01,500],'B365C':[2,3,4]}
  u={};self.assertEqual(before,elo_predictions(altered,trace=u));self.assertEqual(t,u)
 def test_goals_sensitivity_ignores_future_splits(self):
  from sefirot.research import load_csvs
  from sefirot.diagnostics import decay_sensitivity
  rows,_=load_csvs(self.paths);original={'split_seasons':{'TUNE':2022}}
  a=decay_sensitivity(rows,original);altered=copy.deepcopy(rows)
  for r in altered:
   if r['season']>=2023:r['home_goals']=100;r['away_goals']=100;r['y']=1
  self.assertEqual(a,decay_sensitivity(altered,original))
