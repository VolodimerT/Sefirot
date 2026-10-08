"""Forward/selection evaluation without simulated money permissions or results leakage."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from scripts.arena_shadow import run_arena
from scripts.arena_forward import freeze,evaluate,main
from sefirot.contracts import digest,time
from test_arena import sample


def case(mid='arena-test-1', kickoff_offset=0, goals=(2,1)):
    pred,quotes,at=sample()
    pred['sports']['match']['id']=mid
    if kickoff_offset:
        kickoff=time(pred['sports']['match']['kickoff'])+timedelta(days=kickoff_offset)
        pred['sports']['match']['kickoff']=kickoff.isoformat()
    pred.pop('id');pred['id']=digest(pred)
    arena=run_arena(pred,quotes,at)
    result={'match_id':mid,'home_goals':goals[0],'away_goals':goals[1],
            'status':'FINISHED','source':'SYNTHETIC_TEST',
            'finished_at':(time(pred['sports']['match']['kickoff'])+timedelta(hours=2)).isoformat(),
            'received_at':(time(pred['sports']['match']['kickoff'])+timedelta(hours=3)).isoformat()}
    entry={'match_id':mid,'prediction':pred,'quotes':quotes,'arena':arena,'result':result}
    planning={'match_id':mid,'prediction_id':pred['id'],'kickoff':pred['sports']['match']['kickoff']}
    return planning,entry


class ForwardArenaTests(unittest.TestCase):
    def test_normal_two_match_score_counts_selections_and_returns(self):
        a,ar=case('game-a',goals=(2,1))
        b,br=case('game-b',1,goals=(0,3))
        original=copy.deepcopy((a,ar,b,br))
        plan=freeze([b,a],'2026-10-08T08:02:00+00:00')
        report=evaluate(plan,[ar,br])
        self.assertEqual(report['planned'],2)
        self.assertEqual(report['settled'],2)
        self.assertEqual(report['coverage'],1)
        self.assertEqual(report['naive']['selected'],2)
        self.assertEqual(report['arena']['selected'],0)
        self.assertAlmostEqual(report['naive']['unit_stake_pnl'],.1)
        self.assertAlmostEqual(report['paired_unit_profit_delta'],-.1)
        self.assertTrue(report['synthetic'])
        self.assertFalse(report['edge_certified'] or report['monetary_permission'])
        self.assertEqual((a,ar,b,br),original)
        self.assertEqual(report,evaluate(plan,[br,ar]))

    def test_missing_manifest_items_and_results_cannot_disappear(self):
        a,ar=case('game-a')
        b,br=case('game-b',1)
        c,cr=case('game-c',2)
        plan=freeze([a,b,c],'2026-10-08T08:02:00+00:00')
        br['result']=None
        report=evaluate(plan,[ar,br])
        self.assertEqual((report['planned'],report['settled'],report['missing_results'],report['missing_capture']), (3,1,1,1))
        self.assertAlmostEqual(report['coverage'],1/3)
        self.assertIsNone(report['exploratory_95pct_interval'])
        self.assertIsNone(report['rows'][-1]['naive_profit'])

    def test_cannot_add_or_duplicate_or_shift_planned_games(self):
        a,ar=case('game-a')
        plan=freeze([a],'2026-10-08T08:02:00+00:00')
        with self.assertRaisesRegex(ValueError,'duplicate'):
            freeze([a,a],'2026-10-08T08:02:00+00:00')
        with self.assertRaisesRegex(ValueError,'before every kickoff'):
            freeze([a],'2026-10-09T06:00:00+00:00')
        with self.assertRaisesRegex(ValueError,'duplicate'):
            evaluate(plan,[ar,ar])
        _,other=case('outsider')
        with self.assertRaisesRegex(ValueError,'unplanned'):
            evaluate(plan,[ar,other])
        bad=copy.deepcopy(plan);bad['fixtures'][0]['kickoff']='2026-10-09T12:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            evaluate(bad,[ar])

    def test_recompute_price_ev_and_do_not_accept_forged_report(self):
        a,ar=case()
        plan=freeze([a],'2026-10-08T08:02:00+00:00')
        forged=copy.deepcopy(ar)
        forged['arena']['candidate_rows'][0]['ev']=500
        forged['arena']['hash']=digest({k:v for k,v in forged['arena'].items() if k!='hash'})
        with self.assertRaisesRegex(ValueError,'do not reproduce'):
            evaluate(plan,[forged])
        forged=copy.deepcopy(ar)
        forged['arena']['research_focus']='1X2:HOME'
        forged['arena']['hash']=digest({k:v for k,v in forged['arena'].items() if k!='hash'})
        with self.assertRaisesRegex(ValueError,'not reproducible'):
            evaluate(plan,[forged])

    def test_invalid_result_future_data_and_betting_permissions_are_rejected(self):
        a,ar=case()
        plan=freeze([a],'2026-10-08T08:02:00+00:00')
        for mutate in ('early','early_finish','wrong','bool','stake','prematch','quote'):
            bad=copy.deepcopy(ar)
            if mutate=='early':bad['result']['received_at']=a['kickoff']
            elif mutate=='early_finish':bad['result']['finished_at']=a['kickoff']
            elif mutate=='wrong':bad['result']['match_id']='foreign'
            elif mutate=='bool':bad['result']['home_goals']=True
            elif mutate=='stake':
                bad['arena']['stake']=1
                bad['arena']['hash']=digest({k:v for k,v in bad['arena'].items() if k!='hash'})
            elif mutate=='prematch':
                bad['arena']['as_of']=a['kickoff']
                bad['arena']['hash']=digest({k:v for k,v in bad['arena'].items() if k!='hash'})
            else:bad['quotes'][0]['odds']=500
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                evaluate(plan,[bad])

    def test_no_regenerated_hash_can_obscure_different_prediction(self):
        a,ar=case()
        plan=freeze([a],'2026-10-08T08:02:00+00:00')
        bad=copy.deepcopy(ar)
        bad['prediction']['candidates'][0]['base']=[.8,.1,.1]
        with self.assertRaisesRegex(ValueError,'prediction id/hash mismatch'):
            evaluate(plan,[bad])

    def test_output_is_new_file_only_and_no_ledger_is_created(self):
        a,ar=case()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            inp=root/'fixtures.json'; inp.write_text(json.dumps([a]))
            plan=root/'plan.json'
            self.assertEqual(main(['freeze',str(inp),'--created-at','2026-10-08T08:02:00+00:00','--output',str(plan)]),0)
            records=root/'records.json';records.write_text(json.dumps([ar]))
            output=root/'score.json'
            self.assertEqual(main(['score',str(plan),str(records),'--output',str(output)]),0)
            saved=json.loads(output.read_text())
            self.assertEqual(saved['planned'],1)
            self.assertEqual(saved['stake'],0)
            self.assertFalse(any(root.glob('*.sqlite')))
            with self.assertRaises(SystemExit) as e:
                main(['score',str(plan),str(records),'--output',str(output)])
            self.assertEqual(e.exception.code,2)


if __name__=='__main__':unittest.main()
