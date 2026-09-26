import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot_core.markets import Market, settle, probabilities, implied, margin, payoff_ev, fair_odds
from sefirot_core.system import analyze
from sefirot_core.storage import ResearchStore

T = datetime(2026,1,10,tzinfo=timezone.utc)
def ts(delta): return (T+timedelta(days=delta)).isoformat()
def fixture():
    facts = [{'key':f'sports.{k}_team','value':v,'source':'fixture','published_at':ts(-2),
              'received_at':ts(-2),'kind':'FACT'} for k,v in (('home','A'),('away','B'))]
    history=[]
    for i in range(20):
        history.append({'match_id':f'h{i}','kickoff':ts(-70+i),'result_received_at':ts(-69+i),
                        'home_team':'A' if i%2 else 'B','away_team':'B' if i%2 else 'A',
                        'home_goals':i%3,'away_goals':(i+1)%3,'source':'fixture'})
    return {'match_id':'target','kickoff':ts(1),'as_of':ts(-1),'decision_at':ts(-.1),'facts':facts,
            'history':history,'league':'Synthetic','scenario':{'thesis':'uncertain','branches':[
                {'home_goals':0,'away_goals':0,'supports_thesis':True,'rationale':'baseline'}]},
            'tactical_fit':{'supported':True},'public_trap':{'unresolved':False},
            'recheck':{'received_at':ts(-.2),'lineup_confirmed':True,'news_checked':True},
            'price_groups_complete':True,'independent_holdout_validated':True,'calibration_validated':True,
            'quotes':[{'kind':'1X2','side':'HOME','odds':2.5,'received_at':ts(-.3),'bookmaker':'Synthetic','phase':'ENTRY'},
                      {'kind':'TOTAL','side':'OVER','line':2.5,'odds':2.,'received_at':ts(-.3),'bookmaker':'Synthetic'}]}

class MarketTests(unittest.TestCase):
    def test_arithmetic_push(self):
        self.assertAlmostEqual(implied(2),.5)
        self.assertAlmostEqual(margin((2,3,6)),0)
        self.assertAlmostEqual(payoff_ev(.4,.2,3),.4)
        self.assertAlmostEqual(fair_odds(.4,.2),2)
        self.assertEqual(settle(Market('DNB','HOME'),1,1),'PUSH')
        self.assertEqual(settle(Market('HANDICAP','AWAY',1),2,1),'PUSH')
        self.assertEqual(settle(Market('TEAM_TOTAL','HOME_OVER',1.5),2,0),'WIN')
        self.assertEqual(settle(Market('DOUBLE_CHANCE','1X'),1,0),'WIN')
        self.assertEqual(settle(Market('BTTS','NO'),2,0),'WIN')
        self.assertEqual(probabilities(Market('1X2','DRAW'),{(1,1):.5,(2,1):.5}),(.5,0.,.5))
    def test_invalid_inputs(self):
        for fn in (lambda: implied(1),lambda: implied(float('nan')),lambda: margin((2,)),
                   lambda: payoff_ev(.7,.4,2),lambda: Market('EXPRESS','HOME'),
                   lambda: Market('TOTAL','OVER',2.25),lambda: settle(Market('BTTS','YES'),True,0)):
            with self.assertRaises(ValueError): fn()

class SystemTests(unittest.TestCase):
    def test_deterministic_no_execution_and_main_order(self):
        event=fixture()
        a=analyze(event)
        self.assertEqual(a,analyze(copy.deepcopy(event)))
        self.assertEqual([c['kind'] for c in a['candidates']],['1X2','TOTAL'])
        self.assertEqual(a['verdict'],'PASS')
        self.assertEqual(a['stake'],0)
        self.assertIn('NO_CERTIFIED_RELEASE_GATE',a['vetoes'])
        self.assertEqual(sum(a['probability_seal']['1x2']),1.) if sum(a['probability_seal']['1x2'])==1 else self.assertAlmostEqual(sum(a['probability_seal']['1x2']),1.)
    def test_novelty_conflict_fragility(self):
        event=fixture();event['novelty']=['new coach'];event['conflicts']=['lineup disagreement']
        event['scenario']['branches'].append({'home_goals':0,'away_goals':3,'supports_thesis':True,'rationale':'counterexample'})
        a=analyze(event)
        self.assertEqual(a['mode'],'UNKNOWN')
        for code in ('UNKNOWN_MODE','CONFLICT_REQUIRES_NEW_SNAPSHOT','DEATH_TEST_FRAGILITY'):
            self.assertIn(code,a['vetoes'])
    def test_future_data_and_live(self):
        event=fixture();event['facts'][0]['received_at']=ts(2)
        with self.assertRaises(ValueError):analyze(event)
        event=fixture();event['mode']='LIVE'
        with self.assertRaises(ValueError):analyze(event)
        event=fixture();event['quotes'][0]['received_at']=ts(.1)
        with self.assertRaises(ValueError):analyze(event)
    def test_unknown_history_and_weak_evidence(self):
        event=fixture();event['history']=[];event['facts'].append({'key':'sports.lineup','value':'probable','source':'rumor',
            'published_at':ts(-2),'received_at':ts(-2),'kind':'ASSUMPTION'});event['critical_keys']=['sports.lineup']
        a=analyze(event)
        self.assertIn('CRITICAL_ASSUMPTION',a['vetoes'])
        self.assertIn('INSUFFICIENT_TEAM_HISTORY',a['vetoes'])
    def test_store_results_chain_and_clv(self):
        event=fixture();decision=analyze(event)
        with tempfile.TemporaryDirectory() as temp:
            store=ResearchStore(Path(temp)/'research.db')
            store.record(event,decision)
            with self.assertRaises(sqlite3.IntegrityError):store.record(event,decision)
            with self.assertRaises(sqlite3.IntegrityError):store.db.execute('DELETE FROM predictions')
            store.close('target',Market('1X2','HOME'),'Synthetic',2.4,ts(-.05))
            self.assertAlmostEqual(store.clv()[0]['clv'],2.5/2.4-1)
            store.result('target',2,1,ts(2))
            self.assertEqual(len(store.performance()),2)
            self.assertTrue(store.verify_chain())
            with self.assertRaises(sqlite3.IntegrityError):store.result('target',0,0,ts(3))
            store.db.execute("UPDATE audit_logs SET payload='corrupt' WHERE id=1")
            self.assertFalse(store.verify_chain())

if __name__=='__main__': unittest.main()

class GovernanceTests(unittest.TestCase):
    def test_competence_is_contextual_and_cannot_authorize(self):
        from sefirot_core.governance import competence, paired_version_test, classify_error
        c=competence(('league','1X2','baseline'),[.1]*30,[.2]*30)
        self.assertEqual(c.zone,'WORKING');self.assertEqual(c.trust,'MEDIUM')
        self.assertEqual(competence(('league','1X2','baseline'),[.1]*30,[.2]*30,True).zone,'FROZEN')
        self.assertFalse(paired_version_test([.2]*30,[.1]*30)['automatic_release'])
        self.assertEqual(classify_error(outcome='LOSS',thesis_held=False,sources_correct=True,late_information=False,market_terms_correct=True),('SCENARIO',))
