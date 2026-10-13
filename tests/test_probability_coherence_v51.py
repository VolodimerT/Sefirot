"""Settlement geometry constraints, not independent accuracy observations."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.markets import market_of,probabilities
from sefirot.probability_coherence import check_coherence,audit_candidates,MAX_GRID_CELLS


def contract(kind,side,line=None):
    return {'kind':kind,'side':side,**({'line':line} if line is not None else {})}


class SettlementCoherenceTests(unittest.TestCase):
    def conflict(self,markets,vectors):
        saved=copy.deepcopy(vectors)
        r=check_coherence(markets,vectors)
        self.assertEqual(r['status'],'CONFLICT')
        self.assertGreater(r['violation_count'],0)
        self.assertEqual(vectors,saved)
        return r

    def test_known_mutually_exclusive_favorite_probabilities_are_rejected(self):
        self.conflict([contract('1X2','HOME'),contract('1X2','AWAY')],
                      [[.9454545454545454,0.,.0545454545454546]]*2)

    def test_exhaustive_three_way_sum_above_one_is_rejected(self):
        r=self.conflict([contract('1X2',s) for s in ('HOME','DRAW','AWAY')],[[.4,0.,.6]]*3)
        self.assertTrue(any(v['coefficients']==[1,1,1] and v['minimum']==v['maximum']==1
                            for v in r['violations']))

    def test_exhaustive_three_way_sum_below_one_is_rejected(self):
        self.conflict([contract('1X2',s) for s in ('HOME','DRAW','AWAY')],[[.2,0.,.8]]*3)

    def test_overlapping_double_chances_have_multiplicity_two(self):
        markets=[contract('DOUBLE_CHANCE',s) for s in ('1X','X2','12')]
        self.conflict(markets,[[.8,0.,.2]]*3)
        self.assertEqual(check_coherence(markets,[[.7,0.,.3],[.6,0.,.4],[.7,0.,.3]])['status'],
                         'NECESSARY_CONDITIONS_PASS')

    def test_dnb_push_and_draw_are_identical_events(self):
        self.conflict([contract('1X2','DRAW'),contract('DNB','HOME')],[[.3,0.,.7],[.5,.2,.3]])

    def test_under_one_and_a_half_and_btts_yes_are_disjoint(self):
        self.conflict([contract('TOTAL','UNDER',1.5),contract('BTTS','YES')],[[.9,0.,.1]]*2)

    def test_team_total_win_is_subset_of_same_match_total_win(self):
        self.conflict([contract('TEAM_TOTAL','HOME_OVER',1.5),contract('TOTAL','OVER',1.5)],
                      [[.8,0.,.2],[.7,0.,.3]])

    def test_zero_handicap_and_dnb_have_all_same_outcomes(self):
        markets=[contract('DNB','HOME'),contract('HANDICAP','HOME',0.)]
        self.assertEqual(check_coherence(markets,[[.4,.3,.3]]*2)['status'],'NECESSARY_CONDITIONS_PASS')
        self.conflict(markets,[[.4,.3,.3],[.5,.3,.2]])

    def test_half_line_cannot_have_push_mass(self):
        self.conflict([contract('TOTAL','OVER',2.5)],[[.6,.1,.3]])

    def test_zero_total_has_no_negative_goal_loss(self):
        self.conflict([contract('TOTAL','OVER',0.)],[[.5,.3,.2]])
        self.conflict([contract('TOTAL','UNDER',0.)],[[.4,.3,.3]])

    def test_honest_joint_distribution_with_far_outside_grid_scores_passes(self):
        markets=[contract('1X2','DRAW'),contract('DOUBLE_CHANCE','12'),contract('DNB','HOME'),
                 contract('HANDICAP','HOME',-2.),contract('TOTAL','UNDER',3.5),
                 contract('BTTS','YES'),contract('TEAM_TOTAL','AWAY_OVER',2.5)]
        mass={(0,0):.1,(1,2):.2,(10000,9998):.3,(9998,10000):.4}
        vectors=[probabilities(market_of(m),mass) for m in markets]
        r=check_coherence(markets,vectors)
        self.assertEqual(r['status'],'NECESSARY_CONDITIONS_PASS')
        self.assertLess(r['representative_max_score'],10000)
        self.assertFalse(r['joint_distribution_verified'])
        self.assertFalse(r['monetary_permission'])

    def test_outside_bounded_analysis_is_unverified_not_a_success(self):
        r=check_coherence([contract('TOTAL','OVER',1000.)],[[0.,0.,1.]])
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertEqual(r['constraints_checked'],0)
        self.assertGreater(r['grid_cells'],MAX_GRID_CELLS)

    def test_warm_cache_does_not_cache_probabilities_or_verdicts(self):
        markets=[contract('1X2','HOME'),contract('1X2','AWAY')]
        valid=[[.4,0.,.6],[.3,0.,.7]]
        self.assertEqual(check_coherence(markets,valid)['status'],'NECESSARY_CONDITIONS_PASS')
        self.conflict(markets,[[.8,0.,.2],[.8,0.,.2]])
        self.assertEqual(check_coherence(markets,valid)['status'],'NECESSARY_CONDITIONS_PASS')

    def test_roundoff_is_not_interpreted_as_an_edge(self):
        markets=[contract('1X2','HOME'),contract('DNB','HOME')]
        self.assertEqual(check_coherence(markets,[[.4,0.,.6],[.4+1e-12,.3,.3-1e-12]])['status'],
                         'NECESSARY_CONDITIONS_PASS')
        self.conflict(markets,[[.4,0.,.6],[.4+1e-6,.3,.3-1e-6]])

    def test_bool_nan_and_unnormalized_vectors_are_rejected_before_relations(self):
        markets=[contract('1X2','HOME')]
        for vector in ([True,0.,0.],[float('nan'),0.,1.],[.4,0.,.4]):
            with self.subTest(vector=vector),self.assertRaises(ValueError):check_coherence(markets,[vector])

    def test_stress_alignment_cannot_silently_drop_a_scenario(self):
        markets=[contract('1X2','HOME'),contract('DNB','HOME')]
        candidates=[{'market':m,'base':[.4,0.,.6],'stress_probabilities':[[.4,0.,.6]]} for m in markets]
        candidates[1]['stress_probabilities'].append([.4,0.,.6])
        r=audit_candidates(candidates)
        self.assertEqual(r['status'],'UNSUPPORTED')
        self.assertEqual(r['reason'],'STRESS_SCENARIO_ALIGNMENT')

    def test_duplicate_and_unbounded_market_inputs_fail_closed(self):
        market=contract('1X2','HOME')
        for markets in ([market,market],[market]*8):
            with self.subTest(size=len(markets)),self.assertRaises(ValueError):
                check_coherence(markets,[[.4,0.,.6]]*len(markets))


if __name__=='__main__':unittest.main()
