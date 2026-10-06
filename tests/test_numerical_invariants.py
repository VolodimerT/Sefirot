"""Independent closed-form checks; successful arithmetic is not predictive value."""
from math import exp,factorial,log
from pathlib import Path
import random
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.probability import distribution
from sefirot.markets import Market,probabilities,fair_odds,payoff_ev
from sefirot.evaluation import metrics,devig


class NumericalInvariantTests(unittest.TestCase):
    def test_poisson_projections_match_closed_form_across_low_and_high_rates(self):
        rates=(.01,.25,.75,1.35,2.5,5.,12.)
        for home in rates:
            for away in rates:
                mass,tail=distribution(home,away);tolerance=4*tail+2e-12
                with self.subTest(home=home,away=away):
                    self.assertAlmostEqual(sum(mass.values()),1.,places=12)
                    p=probabilities(Market('BTTS','YES'),mass)[0]
                    self.assertLessEqual(abs(p-(1-exp(-home))*(1-exp(-away))),tolerance)
                    for line in (.5,1.5,2.5,5.5):
                        expected=exp(-(home+away))*sum((home+away)**k/factorial(k) for k in range(int(line)+1))
                        observed=probabilities(Market('TOTAL','UNDER',line),mass)[0]
                        self.assertLessEqual(abs(observed-expected),tolerance)
    def test_complementary_contracts_swap_win_and_loss_including_push(self):
        mass,_=distribution(1.7,1.1)
        pairs=[(Market('DNB','HOME'),Market('DNB','AWAY')),(Market('BTTS','YES'),Market('BTTS','NO'))]
        for line in (-2.,-1.5,0.,.5,2.):pairs.append((Market('HANDICAP','HOME',line),Market('HANDICAP','AWAY',-line)))
        for line in (0.,.5,1.,2.5,4.):
            pairs.append((Market('TOTAL','OVER',line),Market('TOTAL','UNDER',line)))
            pairs.append((Market('TEAM_TOTAL','HOME_OVER',line),Market('TEAM_TOTAL','HOME_UNDER',line)))
        for left,right in pairs:
            a=probabilities(left,mass);b=probabilities(right,mass)
            for i,j in ((0,2),(1,1),(2,0)):self.assertAlmostEqual(a[i],b[j],places=12)
        outcomes=[probabilities(Market('1X2',s),mass)[0] for s in ('HOME','DRAW','AWAY')]
        self.assertAlmostEqual(sum(outcomes),1.,places=12)
    def test_fair_prices_break_even_and_ev_matches_direct_unit_payoff(self):
        rng=random.Random(412)
        for _ in range(200):
            win=.001+rng.random()*.998;push=rng.random()*(1-win)*.9
            fair=fair_odds(win,push)
            self.assertAlmostEqual(payoff_ev(win,push,fair),0.,places=12)
            odds=1.01+rng.random()*5
            direct=win*odds+push-1
            self.assertAlmostEqual(payoff_ev(win,push,odds),direct,places=12)
    def test_metrics_match_known_uniform_perfect_and_wrong_predictions(self):
        uniform=metrics([[1/3]*3]*3,[0,1,2])
        self.assertAlmostEqual(uniform['brier'],1/3);self.assertAlmostEqual(uniform['log_loss'],log(3))
        perfect=metrics([[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],[0,1,2])
        self.assertEqual(perfect['brier'],0);self.assertEqual(perfect['log_loss'],0)
        wrong=metrics([[1.,0.,0.]],[1]);self.assertEqual(wrong['brier'],1.)
        self.assertAlmostEqual(wrong['log_loss'],-log(1e-15));self.assertIsNone(wrong['interval_coverage'])
    def test_devig_preserves_order_normalization_and_fair_symmetry(self):
        for method in ('proportional','power','shin'):
            p=devig([2.,3.,4.],method);self.assertAlmostEqual(sum(p),1.,places=10)
            self.assertGreater(p[0],p[1]);self.assertGreater(p[1],p[2])
            fair=devig([3.,3.,3.],method)
            for x in fair:self.assertAlmostEqual(x,1/3,places=10)
