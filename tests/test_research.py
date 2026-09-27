import copy
import csv
from datetime import date,timedelta
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.evaluation import metrics,log_loss,devig,market_consensus
from sefirot.research import load_csvs,elo_predictions,frequency_predictions,temperature,benchmark

class EvaluationTests(unittest.TestCase):
    def test_perfect_and_uniform_scores(self):
        m=metrics([[1,0,0],[0,1,0],[0,0,1]],[0,1,2])
        self.assertEqual(m['brier'],0);self.assertEqual(m['log_loss'],0);self.assertEqual(m['ece_macro'],0)
        self.assertIsNone(m['interval_coverage'])
        m=metrics([[1/3]*3],[1]);self.assertAlmostEqual(m['brier'],1/3);self.assertAlmostEqual(m['log_loss'],math.log(3))
    def test_invalid_and_zero_probabilities(self):
        for p in ([.4,.4,.4],[math.nan,0,1],[-.1,.1,1],[True,0,0]):
            with self.assertRaises(ValueError):metrics([p],[0])
        with self.assertRaises(ValueError):metrics([],[])
        with self.assertRaises(ValueError):log_loss([1,0,0],True)
        self.assertAlmostEqual(log_loss([0,0,1],0),-math.log(1e-15))
    def test_devig_proportional_and_power(self):
        self.assertEqual(devig([3,3,3]),[1/3]*3)
        for odds in ([2,3,4],[4,4,4],[1.01,100,100]):
            for method in ('proportional','power'):
                p=devig(odds,method);self.assertAlmostEqual(sum(p),1);self.assertTrue(all(0<x<1 for x in p))
        with self.assertRaises(ValueError):devig([2,3])
        with self.assertRaises(ValueError):devig([2,3,4],'silent_unknown')
    def test_consensus_separates_best_prices(self):
        r=market_consensus([{'bookmaker':'a','odds':[2,3,4]},{'bookmaker':'b','odds':[2.1,2.8,4.2]}])
        self.assertEqual([b['odds'] for b in r['best']],[2.1,3,4.2]);self.assertAlmostEqual(sum(r['fair_probability']),1)
        with self.assertRaises(ValueError):market_consensus([])
    def test_temperature_one_is_identity(self):
        p=[.2,.3,.5]
        for a,b in zip(p,temperature(p,1)):self.assertAlmostEqual(a,b)
        with self.assertRaises(ValueError):temperature(p,0)

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.paths=[]
        for season in range(2020,2025):
            path=self.root/f'{season}.csv';self.paths.append(path)
            with path.open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['Div','Date','HomeTeam','AwayTeam','FTHG','FTAG','FTR','B365H','B365D','B365A','AvgH','AvgD','AvgA'])
                for i in range(9):
                    h,a=[(2,0),(1,1),(0,1)][i%3]
                    writer.writerow(['E0',(date(season,8,1)+timedelta(days=i)).strftime('%d/%m/%Y'),'A','B',h,a,'HDA'[i%3],2,3,4,2,3,4])
    def tearDown(self):self.temp.cleanup()
    def test_import_preserves_unknown_availability(self):
        rows,data=load_csvs(self.paths);self.assertEqual(len(rows),45);self.assertFalse(data['promotable'])
        self.assertTrue(all(r['result_available_at'] is None and r['odds_observed_at'] is None for r in rows))
        with self.assertRaises(ValueError):load_csvs(self.paths+self.paths[:1])
    def test_future_outcome_cannot_change_previous_forecasts(self):
        rows,_=load_csvs(self.paths);modified=copy.deepcopy(rows);modified[-1]['y']=0
        self.assertEqual(elo_predictions(rows),elo_predictions(modified))
        self.assertEqual(frequency_predictions(rows),frequency_predictions(modified))
    def test_same_day_result_is_unavailable(self):
        rows,_=load_csvs(self.paths);rows=rows[:2];rows[1]['date']=rows[0]['date']
        baseline=elo_predictions(rows);rows[0]['y']=2
        self.assertEqual(baseline,elo_predictions(rows))
    def test_full_pipeline_and_final_outcomes_do_not_tune(self):
        r=benchmark(self.paths,self.root/'a.json')
        self.assertFalse(r['monetary_permission']);self.assertEqual(r['status'],'EXPERIMENTAL');self.assertEqual(r['split_counts']['TEST'],9)
        with self.assertRaises(ValueError):benchmark(self.paths,self.root/'a.json')
        p=self.paths[-1];s=p.read_text().replace(',2,0,H,',',0,2,A,');p.write_text(s)
        other=benchmark(self.paths,self.root/'b.json')
        self.assertEqual(r['selected'],other['selected']);self.assertEqual(r['temperature'],other['temperature'])
    def test_exactly_five_seasons(self):
        with self.assertRaises(ValueError):benchmark(self.paths[:4],self.root/'bad.json')
    def test_reproducible_content_hash(self):
        a=benchmark(self.paths,self.root/'a.json');b=benchmark(self.paths,self.root/'b.json')
        self.assertEqual(a['run_id'],b['run_id'])

if __name__=='__main__':unittest.main()
