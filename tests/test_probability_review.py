"""Audit regression cases; controlled proofs are fictional, not money validation."""
import copy
from math import exp
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src')]
from sefirot.contracts import Policy
from sefirot.decision_card import render_card
from sefirot.engine import prepare
from sefirot.fixtures import example
from sefirot.markets import market_of,probabilities,settle
from sefirot.probability import distribution
from sefirot.probability_review import scoring_ceiling,under_ceiling
from test_audit_upgrade import controlled,decision,NOW


class DivergenceBoundaryTests(unittest.TestCase):
    def only_one_source(self,win):
        p,case,quotes,context=controlled(win=win,odds=2.)
        case['recheck']['evidence']=[e for e in case['recheck']['evidence'] if not e['id'].endswith('-independent')]
        return p,case,quotes,context

    def test_decimal_ten_points_requires_corroboration_despite_float_roundoff(self):
        out=decision(*self.only_one_source(.6))
        self.assertLess(out['candidates'][0]['market_reference']['divergence'],.10)
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['risk']['stake'],0.)
        self.assertIn('DIVERGENCE_NEEDS_CORROBORATION',out['limiting_factors'])
        row=out['decision_card']['alternatives'][0]
        self.assertEqual(row['divergence_review']['status'],'CORROBORATION_REQUIRED')
        self.assertEqual(out['candidates'][0]['corroboration']['status'],'INSUFFICIENT')

    def test_twenty_points_is_extreme_even_with_independent_corroboration(self):
        out=decision(*controlled(win=.7,odds=2.))
        self.assertEqual(out['candidates'][0]['corroboration']['status'],'CURRENT_FACTS_CORROBORATED')
        self.assertEqual(out['decision'],'PASS');self.assertEqual(out['risk']['stake'],0.)
        self.assertIn('MODEL_MARKET_DIVERGENCE',out['limiting_factors'])
        self.assertIn('PROBABILITY_RECALCULATION_REQUIRED',out['limiting_factors'])
        self.assertEqual(out['decision_card']['alternatives'][0]['divergence_review']['status'],'EXTREME_RECALCULATE')

    def test_ten_points_can_pass_existing_gates_with_independent_facts(self):
        out=decision(*controlled(win=.6,odds=2.))
        self.assertEqual(out['decision'],'BET')
        self.assertEqual(out['candidates'][0]['corroboration']['status'],'CURRENT_FACTS_CORROBORATED')
        self.assertEqual(out['decision_card']['alternatives'][0]['divergence_review']['status'],'CORROBORATION_REQUIRED')
        self.assertNotIn('DIVERGENCE_NEEDS_CORROBORATION',out['limiting_factors'])

    def test_materially_below_review_threshold_does_not_trigger_boundary_allowance(self):
        out=decision(*self.only_one_source(.59999999))
        self.assertEqual(out['decision'],'BET')
        self.assertEqual(out['candidates'][0]['corroboration']['status'],'NOT_REQUIRED')

    def test_negative_boundary_also_requires_fresh_independent_groups(self):
        p,case,quotes,context=self.only_one_source(.4)
        out=decision(p,case,quotes,context)
        self.assertIn('DIVERGENCE_NEEDS_CORROBORATION',out['limiting_factors'])
        self.assertEqual(out['decision_card']['alternatives'][0]['divergence_review']['status'],'CORROBORATION_REQUIRED')

    def test_two_source_names_in_same_independence_group_are_not_two_confirmations(self):
        p,case,quotes,context=controlled(win=.6,odds=2.)
        p['sports']['sources'][1]['independence_group']=p['sports']['sources'][0]['independence_group']
        out=decision(p,case,quotes,context)
        self.assertIn('DIVERGENCE_NEEDS_CORROBORATION',out['limiting_factors'])
        self.assertTrue(all(len(v)==1 for v in out['candidates'][0]['corroboration']['independence_groups'].values()))


class TrustDisclosureTests(unittest.TestCase):
    def test_large_ev_and_positive_stress_cannot_replace_missing_holdout(self):
        p,case,quotes,context=controlled(win=.6,odds=2.)
        context['releases']={};out=decision(p,case,quotes,context)
        row=out['decision_card']['alternatives'][0];trust=row['probability_trust']
        self.assertGreater(row['ev'],0);self.assertGreater(row['stress_ev_min'],0)
        self.assertEqual(trust['status'],'BLOCKED');self.assertIn('HOLDOUT_UNVALIDATED',trust['blockers'])
        self.assertEqual(out['decision'],'PASS');self.assertNotEqual(out['class'],'A')
        self.assertIsNone(trust['score']);self.assertFalse(trust['monetary_permission'])

    def test_trust_exists_before_price_and_does_not_turn_missing_price_into_bad_data(self):
        p,case,quotes,context=controlled()
        out=decision(p,case,[],context);trust=out['decision_card']['alternatives'][0]['probability_trust']
        self.assertEqual(trust['status'],'EXISTING_GATES_PASSED')
        self.assertNotIn('MISSING_CURRENT_PRICE',trust['blockers'])
        self.assertEqual(out['decision'],'PASS');self.assertIsNone(trust['true_probability_accuracy'])

    def test_price_change_does_not_improve_unvalidated_calibration_or_history(self):
        p,case,quotes,context=controlled();p['candidates'][0]['calibration']='UNCALIBRATED'
        first=decision(p,case,quotes,context)['decision_card']['alternatives'][0]['probability_trust']
        quotes[0]['odds']=1.6
        second=decision(p,case,quotes,context)['decision_card']['alternatives'][0]['probability_trust']
        self.assertEqual(first['components'],second['components'])
        self.assertIn('CALIBRATION_INSUFFICIENT',second['blockers']);self.assertEqual(second['status'],'BLOCKED')

    def test_missing_recheck_lineup_blocks_trust_even_with_high_ev(self):
        p,case,quotes,context=controlled()
        case['recheck']['evidence']=[e for e in case['recheck']['evidence'] if e['key']!='lineup']
        out=decision(p,case,quotes,context);trust=out['decision_card']['alternatives'][0]['probability_trust']
        self.assertEqual(trust['components']['lineup']['status'],'BLOCKED')
        self.assertIn('MISSING_LINEUP',trust['blockers']);self.assertEqual(out['decision'],'PASS')

    def test_synthetic_data_is_never_disclosed_as_validated_probability(self):
        p,case,quotes,context=controlled();p['synthetic']=True
        out=decision(p,case,quotes,context)
        self.assertEqual(out['decision_card']['alternatives'][0]['probability_trust']['status'],'BLOCKED')
        self.assertEqual(out['decision'],'PASS')

    def test_new_fields_are_deterministic_do_not_mutate_seal_and_do_not_invent_narrative_data(self):
        p,case,quotes,context=controlled();original=copy.deepcopy(p)
        a=decision(p,case,quotes,context);b=decision(p,case,quotes,context)
        self.assertEqual(a,b);self.assertEqual(p,original)
        self.assertEqual(a['decision_card']['alternatives'][0]['public_trap']['narrative_dependence'],'NOT_QUANTIFIED')
        self.assertIn('Доверие к вероятности',render_card(a['decision_card']))


class SearchDisclosureTests(unittest.TestCase):
    def test_reference_quotes_do_not_expand_the_predeclared_candidate_pool(self):
        p,case,quotes,context=controlled(win=.6,odds=2.)
        quotes.extend({**quotes[0],'market':{'kind':'1X2','side':side},'odds':odd} for side,odd in [('DRAW',4.),('AWAY',4.)])
        out=decision(p,case,quotes,context);review=out['decision_card']['search_review']
        self.assertEqual(review['sealed_market_count'],1);self.assertEqual(review['evaluated_market_count'],1)
        self.assertEqual(review['priced_market_count'],1);self.assertEqual(review['quoted_contract_count'],3)
        self.assertEqual(review['reference_only_contract_count'],2)
        self.assertIsNone(review['other_screened_fixtures']);self.assertIsNone(review['search_bias_penalty'])

    def test_sealed_ordinal_keeps_unpriced_alternatives_and_is_not_an_empirical_penalty(self):
        markets=[{'kind':'1X2','side':'HOME'},{'kind':'TOTAL','side':'OVER','line':2.5}]
        p,case,quotes,context=controlled(markets,win=.6,odds=2.)
        out=decision(p,case,quotes[1:],context);review=out['decision_card']['search_review']
        self.assertEqual(review['sealed_market_count'],2);self.assertEqual(review['priced_market_count'],1)
        self.assertEqual(review['focus_sealed_ordinal'],2)
        self.assertEqual(review['focus_market'],'TOTAL:OVER:2.5')
        self.assertFalse(review['monetary_permission'])


class CeilingProjectionTests(unittest.TestCase):
    def test_raw_three_and_four_goal_projections_match_poisson_cdf(self):
        mass,_=distribution(1.7,1.2);out=scoring_ceiling(mass)
        for side,rate in [('home',1.7),('away',1.2)]:
            for threshold in (3,4):
                term=exp(-rate);cdf=term
                for k in range(1,threshold):term*=rate/k;cdf+=term
                self.assertAlmostEqual(out['teams'][side][f'p{threshold}_plus'],1-cdf,places=7)
        self.assertFalse(out['automatic_veto']);self.assertFalse(out['monetary_permission'])

    def test_integer_under_counts_four_goals_as_loss_and_three_as_possible_push(self):
        mass={(3,0):.3,(4,0):.2,(0,4):.1,(4,4):.1,(0,0):.3}
        m=market_of({'kind':'TOTAL','side':'UNDER','line':3.})
        out=under_ceiling(m,mass);self.assertEqual(out['loss_goal_threshold'],4)
        self.assertEqual(settle(m,3,0),'PUSH')
        self.assertAlmostEqual(out['one_team_alone_loss_probability']['home'],.3)
        self.assertAlmostEqual(out['either_relevant_team_alone_loss_probability'],.4)
        self.assertLess(out['either_relevant_team_alone_loss_probability'],sum(out['one_team_alone_loss_probability'].values()))

    def test_half_under_and_team_under_respect_the_exact_contract(self):
        mass={(3,0):.4,(0,4):.2,(0,0):.4}
        total=under_ceiling(market_of({'kind':'TOTAL','side':'UNDER','line':2.5}),mass)
        team=under_ceiling(market_of({'kind':'TEAM_TOTAL','side':'HOME_UNDER','line':2.5}),mass)
        self.assertAlmostEqual(total['either_relevant_team_alone_loss_probability'],.6)
        self.assertEqual(set(team['one_team_alone_loss_probability']),{'home'})
        self.assertAlmostEqual(team['either_relevant_team_alone_loss_probability'],.4)

    def test_projection_is_sealed_before_price_and_does_not_relabel_raw_as_calibrated(self):
        case=example(NOW);market={'kind':'TOTAL','side':'UNDER','line':3.}
        p=prepare(case['sports'],[market],Policy())
        self.assertIn('p4_plus',p['scoring_ceiling']['teams']['home'])
        self.assertIn('ORIGINAL_RAW_SCORE_MASS',p['candidates'][0]['under_ceiling']['basis'])
        self.assertFalse(p['scoring_ceiling']['automatic_veto'])
        self.assertAlmostEqual(p['candidates'][0]['raw'][0]+p['candidates'][0]['raw'][1]+p['candidates'][0]['raw'][2],1.)

    def test_projection_rejects_bad_score_mass_and_over_has_no_under_diagnostic(self):
        for mass in [{},{(0,0):.5},{(-1,0):1.},{(True,0):1.}]:
            with self.assertRaises(ValueError):scoring_ceiling(mass)
        self.assertIsNone(under_ceiling(market_of({'kind':'TOTAL','side':'OVER','line':2.5}),{(0,0):1.}))
