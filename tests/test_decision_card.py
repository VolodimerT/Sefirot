"""Controlled admission cases and exact price arithmetic; no real-match retuning."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sefirot.contracts import Policy
from sefirot.decision_card import render_card
from sefirot.markets import payoff_ev
from sefirot.probability import ev_bounds,price_requirements,worst_case_probabilities
from sefirot.repository import Repository
from test_audit_upgrade import controlled,decision,NOW


class PriceRequirementsTests(unittest.TestCase):
    def test_integer_line_push_changes_fair_and_entry_threshold(self):
        p=[.4,.3,.3]
        requirements=price_requirements(p,p,p,[p],Policy())
        self.assertAlmostEqual(requirements['base_min_odds'],1.8)
        self.assertAlmostEqual(requirements['required_odds'],1.8)
        self.assertAlmostEqual(payoff_ev(p[0],p[1],1.8),.02)
        self.assertFalse(requirements['monetary_permission'])

    def test_threshold_clears_every_feasible_probability_not_component_lows(self):
        low=[.3,.1,.2];high=[.5,.5,.4];base=[.4,.3,.3];stress=[[.3,.4,.3]]
        requirements=price_requirements(base,low,high,stress,Policy())
        self.assertAlmostEqual(requirements['low_min_odds'],1+.4/.3)
        price=requirements['required_odds']
        for w in range(30,51):
            for push in range(10,51):
                p=[w/100,push/100,1-(w+push)/100]
                if low[2]<=p[2]<=high[2]:self.assertGreaterEqual(payoff_ev(p[0],p[1],price),-1e-12)
        self.assertLess(ev_bounds(low,high,price-.0001)[0],0)

    def test_stress_threshold_dominates_and_is_not_probability_interval(self):
        p=[.6,0,.4];stress=[[.4,0,.6]]
        requirements=price_requirements(p,p,p,stress,Policy())
        self.assertAlmostEqual(requirements['stress_min_odds'],2.5)
        self.assertAlmostEqual(requirements['required_odds'],2.5)
        self.assertLess(payoff_ev(.4,0,2.49),0)

    def test_no_finite_price_when_loss_possible_with_zero_win(self):
        p=[.6,0,.4]
        requirements=price_requirements(p,[0,0,0],[1,1,1],[p],Policy())
        self.assertIsNone(requirements['low_min_odds']);self.assertIsNone(requirements['required_odds'])
        self.assertNotIn('Infinity',json.dumps(requirements,allow_nan=False))

    def test_all_push_is_not_positive_value(self):
        p=[0,1,0]
        requirements=price_requirements(p,p,p,[p],Policy())
        self.assertIsNone(requirements['base_min_odds']);self.assertEqual(requirements['stress_min_odds'],1)

    def test_bad_probability_inputs_fail_closed(self):
        p=[.6,0,.4]
        for base,low,high,stress in (([.6,0,.6],p,p,[p]),(p,[.8,0,.3],[.9,0,.4],[p]),
                                   (p,p,p,[]),(p,p,p,[[.5,0,.7]]),(p,p,p,[[True,0,0]])):
            with self.assertRaises(ValueError):price_requirements(base,low,high,stress,Policy())


class FinalDecisionTests(unittest.TestCase):
    def test_bet_card_has_one_selected_market_and_exact_stake(self):
        p,case,quotes,context=controlled();out=decision(p,case,quotes,context);card=out['decision_card']
        self.assertEqual(card['status'],'BET');self.assertEqual(card['verdict_ru'],'играбельно')
        self.assertEqual(sum(r['admission_permission'] for r in card['alternatives']),1)
        self.assertEqual(card['stake'],out['risk']['stake']);self.assertFalse(card['execution_enabled'])

    def test_paid_taunton_pattern_visible_without_overriding_stress_veto(self):
        p,case,quotes,context=controlled(win=1.1273/2.30,odds=2.30)
        c=p['candidates'][0];c['stress_probabilities']=[[.9387/2.30,0,1-.9387/2.30]]
        out=decision(p,case,quotes,context);card=out['decision_card'];candidate=card['research_candidate']
        self.assertEqual(out['decision'],'PASS');self.assertEqual(card['status'],'PRICE_FRAGILE')
        self.assertAlmostEqual(candidate['ev'],.1273);self.assertEqual(candidate['stress_class'],'FRAGILE_VALUE')
        self.assertAlmostEqual(candidate['price_requirements']['stress_min_odds'],2.30/.9387)
        self.assertFalse(candidate['admission_permission']);self.assertEqual(card['stake'],0)
        self.assertIn('DEATH_TEST_PRICE_FRAGILITY',out['limiting_factors'])

    def test_tamworth_pattern_gets_aggressive_label_and_no_stake(self):
        p,case,quotes,context=controlled(win=1.0305/1.91,odds=1.91)
        p['candidates'][0]['stress_probabilities']=[[.868/1.91,0,1-.868/1.91]]
        out=decision(p,case,quotes,context)
        self.assertEqual(out['decision_card']['research_candidate']['stress_class'],'AGGRESSIVE_VALUE')
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['risk']['stake'],0)

    def test_no_edge_and_no_data_are_different_reasons_for_pass(self):
        p,case,quotes,context=controlled(win=.48,odds=2.)
        out=decision(p,case,quotes,context);self.assertEqual(out['decision_card']['status'],'NO_EDGE')
        self.assertIsNone(out['decision_card']['research_candidate'])
        p['candidates'][0]['calibration']='UNCALIBRATED'
        out=decision(p,case,quotes,context);self.assertEqual(out['decision_card']['status'],'NOT_EVALUABLE')

    def test_missing_price_does_not_hide_missing_model_validation(self):
        p,case,quotes,context=controlled();p['candidates'][0]['calibration']='UNCALIBRATED'
        out=decision(p,case,[],context)
        self.assertIn('CALIBRATION_INSUFFICIENT',out['limiting_factors'])
        self.assertIn('MISSING_CURRENT_PRICE',out['limiting_factors'])
        self.assertEqual(out['decision_card']['status'],'NOT_EVALUABLE')

    def test_global_veto_is_attached_to_each_candidate(self):
        p,case,quotes,context=controlled();context['policy_approved']=False
        out=decision(p,case,quotes,context);card=out['decision_card']
        self.assertEqual(card['status'],'NOT_EVALUABLE');self.assertEqual(card['stake'],0)
        self.assertIn('POLICY_NOT_APPROVED',card['alternatives'][0]['effective_blockers'])
        self.assertFalse(card['alternatives'][0]['price_only_recheck'])
        self.assertIsNone(out['selected_market']);self.assertEqual(out['screened_market'],p['candidates'][0]['key'])

    def test_extreme_divergence_has_recalculation_action_not_odds_trigger(self):
        p,case,quotes,context=controlled(win=.95,odds=2.)
        out=decision(p,case,quotes,context);card=out['decision_card']
        self.assertEqual(card['status'],'RECALCULATE');self.assertFalse(card['alternatives'][0]['price_only_recheck'])
        self.assertEqual(out['risk']['stake'],0)

    def test_ranking_does_not_prefer_market_family_over_conservative_ev(self):
        p,case,quotes,context=controlled([{'kind':'1X2','side':'HOME'},{'kind':'TEAM_TOTAL','side':'HOME_OVER','line':1.5}],win=.65,odds=1.7)
        total=p['candidates'][1]
        total.update(base=[.7,0,.3],low=[.68,0,.28],high=[.72,0,.32],stress_probabilities=[[.69,0,.31]])
        out=decision(p,case,quotes,context)
        self.assertEqual(out['decision'],'BET');self.assertEqual(out['selected_market'],total['key'])

    def test_risk_uses_feasible_adverse_distribution_for_push_market(self):
        p,case,quotes,context=controlled([{'kind':'DNB','side':'HOME'}],odds=1.6)
        c=p['candidates'][0]
        c.update(base=[.45,.4,.15],low=[.4,.3,.1],high=[.5,.5,.2],stress_probabilities=[[.4,.4,.2]])
        # Component lows yield -6% EV if used as a synthetic standalone vector.
        self.assertLess(payoff_ev(.4,.3,1.6),0)
        out=decision(p,case,quotes,context)
        self.assertEqual(out['decision'],'BET');self.assertGreater(out['risk']['stake'],0)
        adverse=out['risk']['probabilities_used'];self.assertAlmostEqual(sum(adverse),1)
        self.assertAlmostEqual(payoff_ev(adverse[0],adverse[1],1.6),out['candidates'][0]['ev_low'])

    def test_exact_ev_tie_prefers_less_loss_with_push_protection(self):
        p,case,quotes,context=controlled([{'kind':'1X2','side':'HOME'},{'kind':'DNB','side':'HOME'}])
        for c,q,base,odd in zip(p['candidates'],quotes,([.5,0,.5],[.25,.5,.25]),(2.5,3.)):
            c.update(base=base,low=base,high=base,stress_probabilities=[base]);q['odds']=odd
        out=decision(p,case,quotes,context)
        self.assertEqual(out['decision'],'BET');self.assertEqual(out['selected_market'],'DNB:HOME')
        self.assertEqual(out['candidates'][0]['ev_low'],out['candidates'][1]['ev_low'])

    def test_worst_case_lies_inside_all_bounds(self):
        low=[.4,.3,.1];high=[.5,.5,.2];p=worst_case_probabilities(low,high,1.6)
        self.assertAlmostEqual(sum(p),1)
        self.assertTrue(all(l-1e-12<=v<=h+1e-12 for l,v,h in zip(low,p,high)))
        self.assertAlmostEqual(payoff_ev(p[0],p[1],1.6),.04)

    def test_risk_limit_does_not_turn_an_admissible_market_into_permission(self):
        p,case,quotes,context=controlled()
        context['exposures']=[{'at':case['decision_at'],'stake':5,'groups':['match:'+p['sports']['match']['id']]}]
        out=decision(p,case,quotes,context)
        self.assertEqual(out['decision_card']['status'],'RISK_LIMIT')
        self.assertEqual(out['risk']['stake'],0);self.assertFalse(out['decision_card']['alternatives'][0]['admission_permission'])

    def test_card_reproducible_and_does_not_change_probability_seal(self):
        p,case,quotes,context=controlled();saved=copy.deepcopy(p)
        first=decision(p,case,quotes,context);second=decision(p,case,quotes,context)
        self.assertEqual(first,second);self.assertEqual(p,saved)
        self.assertFalse(first['decision_card']['result_data_used'])

    def test_russian_render_does_not_present_blocked_candidate_as_bet(self):
        p,case,quotes,context=controlled();context['policy_approved']=False
        rendered=render_card(decision(p,case,quotes,context)['decision_card'])
        self.assertIn('пропуск',rendered);self.assertIn('допуска нет',rendered)
        self.assertIn('версия политики не утверждена',rendered);self.assertNotIn('Выбранный рынок:',rendered)


class ExplainCommandTests(unittest.TestCase):
    def test_demo_text_is_concise_russian_and_still_passes_synthetic_data(self):
        run=subprocess.run([sys.executable,str(ROOT/'sefirot.py'),'demo','--text'],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertIn('Вердикт: пропуск',run.stdout)
        self.assertNotIn('prediction_id',run.stdout)

    def test_explain_is_read_only_and_preserves_recorded_card(self):
        p,case,quotes,context=controlled();out=decision(p,case,quotes,context)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'ledger.sqlite';repo=Repository(path)
            # The minimal records only test the read-only projection, not ledger integrity.
            repo.db.execute('PRAGMA foreign_keys=OFF')
            repo.insert('decisions','test-id',out,prediction_id='controlled',at=NOW.isoformat());repo.close()
            before=path.read_bytes()
            args=[sys.executable,str(ROOT/'sefirot.py'),'--db',str(path),'explain','test-id']
            run=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout),out['decision_card'])
            self.assertEqual(before,path.read_bytes())
            run=subprocess.run(args+['--text'],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);self.assertIn('Вердикт: играбельно',run.stdout)
            self.assertEqual(before,path.read_bytes())

    def test_explain_missing_ledger_cannot_create_it(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'absent.sqlite'
            run=subprocess.run([sys.executable,str(ROOT/'sefirot.py'),'--db',str(path),'explain','id'],capture_output=True,text=True)
            self.assertEqual(run.returncode,2);self.assertFalse(path.exists())


if __name__=='__main__':unittest.main()
