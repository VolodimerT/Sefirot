"""Small synthetic CSVs verify split mechanics, not predictive efficacy."""
import copy
import csv
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import Policy
from sefirot.goal_research import benchmark_upgrade, validate_design
from sefirot.research import load_csvs


class GoalBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.paths=[]
        self.policy=replace(Policy(),goal_model='SOS_THRESHOLD_V2',stress_mode='GRADED',
                            min_profile_games=1,min_threshold_bin=2,min_calibration=2)
        for year in range(2020,2025):
            path=self.root/f'{year}.csv';self.paths.append(path)
            with path.open('w',newline='') as file:
                writer=csv.writer(file)
                writer.writerow(['Div','Date','HomeTeam','AwayTeam','FTHG','FTAG','FTR','B365H','B365D','B365A'])
                for i in range(12):
                    h,a=((2,0),(1,1),(0,1))[i%3]
                    teams=('A','B') if i%2==0 else ('C','D')
                    writer.writerow(['E0',(date(year,8,1)+timedelta(days=i//2)).strftime('%d/%m/%Y'),*teams,h,a,'HDA'[i%3],2,3,4])

    def tearDown(self):self.temp.cleanup()

    def design(self):
        _,data=load_csvs(self.paths)
        return {'version':'p0-upgrade-design-v1','profile':'MEN','warmup_seasons':[2020],
                'train_seasons':[2021,2022],'count_calibration_season':2023,'count_calibration_fraction':.5,
                'test_seasons':[2024],'test_already_viewed':True,'primary_market':'TEAM_TOTAL:HOME_OVER:1.5',
                'policy_hash':self.policy.fingerprint,'sources':[{'file':s['file'],'sha256':s['sha256']} for s in data['sources']],
                'monetary_permission':False}

    def run_benchmark(self,name):return benchmark_upgrade(self.paths,self.design(),self.root/name,self.policy)

    def test_frozen_splits_and_output_do_not_create_monetary_permission(self):
        result=self.run_benchmark('a')
        self.assertEqual(result['split_counts'],{'WARMUP':12,'TRAIN':24,'COUNT_CALIBRATION':6,'MARKET_CALIBRATION':6,'TEST':12})
        self.assertEqual(result['status'],'HISTORICAL_HOLDOUT_ALREADY_VIEWED')
        self.assertFalse(result['can_certify_release']);self.assertFalse(result['monetary_permission'])
        self.assertEqual(result['comparison']['n'],12)
        self.assertEqual(len(result['market_metrics']),7)
        self.assertTrue((self.root/'a'/'GOAL_MODEL.json').exists())
        with self.assertRaises(ValueError):self.run_benchmark('a')

    def test_results_and_hashes_are_reproducible(self):
        self.assertEqual(self.run_benchmark('a'),self.run_benchmark('b'))

    def test_final_same_day_outcome_cannot_tune_or_change_any_test_prediction(self):
        before=self.run_benchmark('a')
        path=self.paths[-1]
        with path.open(newline='') as file:rows=list(csv.reader(file))
        rows[-2][4:7]=['9','0','H']
        with path.open('w',newline='') as file:csv.writer(file).writerows(rows)
        after=self.run_benchmark('b')
        self.assertEqual(before['artifact_hash'],after['artifact_hash'])
        self.assertEqual(before['calibrator_hashes'],after['calibrator_hashes'])
        for old,new in zip(before['predictions'],after['predictions']):
            self.assertEqual(old['rates'],new['rates']);self.assertEqual(old['thresholds'],new['thresholds'])
            for key in old['markets']:
                for model in ('baseline','candidate'):
                    self.assertEqual(old['markets'][key][model]['probabilities'],new['markets'][key][model]['probabilities'])
        self.assertNotEqual(before['run_id'],after['run_id'])

    def test_prices_never_enter_model_or_calibrator_fit(self):
        before=self.run_benchmark('a')
        for path in self.paths:
            with path.open(newline='') as file:rows=list(csv.reader(file))
            for row in rows[1:]:row[7]='100'
            with path.open('w',newline='') as file:csv.writer(file).writerows(rows)
        after=self.run_benchmark('b')
        self.assertEqual(before['artifact_hash'],after['artifact_hash'])
        self.assertEqual(before['calibrator_hashes'],after['calibrator_hashes'])
        self.assertEqual(before['comparison'],after['comparison'])

    def test_mutated_source_overlap_or_policy_is_rejected(self):
        rows,data=load_csvs(self.paths)
        for field,value in (('policy_hash','wrong'),('test_seasons',[2022,2024]),('monetary_permission',True)):
            design=self.design();design[field]=value
            with self.assertRaises(ValueError):validate_design(rows,data,design,self.policy)
        design=self.design();design['sources'][0]['sha256']='wrong'
        with self.assertRaises(ValueError):validate_design(rows,data,design,self.policy)


if __name__=='__main__':unittest.main()
