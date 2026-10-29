"""Numerical regressions, never additional football observations or a fit."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from math import fsum, ulp
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import Policy, digest, time
from sefirot.engine import prepare
from sefirot.fixtures import example
from sefirot.identity import model_code_hash
from sefirot.markets import Market, probabilities, settle
from sefirot.probability import CALIBRATION_SCHEMA, calibrate, distribution, poisson
from sefirot.repository import Repository
from sefirot.service import Service

NOW = datetime(2026, 10, 13, 7, tzinfo=timezone.utc)
OLD_MODEL_HASH = '2b4b6e396d34cf74132a3bfead508ab71d1f4df0caefd753e845ee7d056b1300'
RATES = (.01, .1, .3, .5, 1., 1.1, 1.35, 2., 3., 6., 12.)


class ProbabilitySummationTests(unittest.TestCase):
    def test_saturated_poisson_category_can_enter_strict_calibration(self):
        mass, _ = distribution(1.35, 1.35)
        market = Market('TOTAL', 'UNDER', 1000.)
        raw = probabilities(market, mass)
        self.assertTrue(all(0 <= p <= 1 for p in raw))
        self.assertEqual(calibrate(market, raw, None, Policy())['status'], 'UNCALIBRATED')

    def test_extreme_total_team_and_handicap_categories_across_rates(self):
        markets = [Market('TOTAL', side, 1000.) for side in ('OVER', 'UNDER')]
        markets += [Market('TEAM_TOTAL', side, 1000.) for side in
                    ('HOME_OVER', 'HOME_UNDER', 'AWAY_OVER', 'AWAY_UNDER')]
        markets += [Market('HANDICAP', 'HOME', line) for line in (-1000., 1000.)]
        for home in RATES:
            for away in RATES:
                mass, _ = distribution(home, away)
                for market in markets:
                    with self.subTest(home=home, away=away, market=market.key):
                        raw = probabilities(market, mass)
                        self.assertTrue(all(0 <= p <= 1 for p in raw))
                        self.assertAlmostEqual(fsum(raw), 1., places=14)
                        calibrate(market, raw, None, Policy())

    def test_projection_is_independent_of_score_insertion_order(self):
        mass, _ = distribution(.3, .5)
        saved = copy.deepcopy(mass)
        reverse = dict(reversed(tuple(mass.items())))
        for market in (Market('TOTAL', 'UNDER', 1000.), Market('TOTAL', 'OVER', 2.5),
                       Market('1X2', 'HOME'), Market('DNB', 'HOME')):
            self.assertEqual(probabilities(market, mass), probabilities(market, reverse))
        self.assertEqual(mass, saved)

    def test_projections_match_high_precision_sum_of_same_input_cells(self):
        mass, _ = distribution(1.35, .5)
        markets = (Market('1X2', 'HOME'), Market('DNB', 'AWAY'),
                   Market('TOTAL', 'OVER', 2.), Market('BTTS', 'YES'))
        with localcontext() as ctx:
            ctx.prec = 80
            for market in markets:
                reference = tuple(float(sum((Decimal.from_float(p) for score, p in mass.items()
                                             if settle(market, *score) == outcome), Decimal(0)))
                                  for outcome in ('WIN', 'PUSH', 'LOSS'))
                self.assertEqual(probabilities(market, mass), reference)

    def test_small_real_loss_probability_is_not_rounded_away(self):
        mass = {(1, 0): 1.-1e-12, (0, 1): 1e-12}
        self.assertEqual(probabilities(Market('1X2', 'HOME'), mass), (1.-1e-12, 0., 1e-12))

    def test_many_score_cells_beyond_cache_limit_use_same_stable_projection(self):
        mass = {(i, 0): 1/5000 for i in range(5000)}
        self.assertEqual(probabilities(Market('TOTAL', 'UNDER', 10000.), mass), (1., 0., 0.))

    def test_machine_boundary_does_not_admit_material_excess_mass(self):
        market = Market('TOTAL', 'UNDER', 1000.)
        # Each individual input is valid; only aggregation introduces the ULP.
        raw = probabilities(market, {(0, 0): .5, (1, 0): .5+ulp(1.)})
        self.assertEqual(raw, (1., 0., 0.))
        for mass in ({(0, 0): .5, (1, 0): .5+1e-9},
                     {(0, 0): 1.+ulp(1.)}, {(0, 0): 1e308, (1, 0): 1e308}):
            with self.subTest(mass=mass), self.assertRaises(ValueError):
                probabilities(market, mass)

    def test_warm_settlement_cache_still_validates_current_mass_and_scores(self):
        market = Market('1X2', 'HOME')
        self.assertEqual(probabilities(market, {(1, 0): .6, (0, 1): .4}), (.6, 0., .4))
        for mass in ({(1, 0): True, (0, 1): 0.}, {(1, 0): -1., (0, 1): 2.},
                     {(1, 0): float('nan'), (0, 1): .4},
                     {(True, 0): .6, (0, 1): .4}, {(1., 0): .6, (0, 1): .4},
                     {(1, 0): .3, (0, 1): .4}):
            with self.subTest(mass=mass), self.assertRaises(ValueError): probabilities(market, mass)

    def test_poisson_tail_remains_explicit_and_is_not_folded_into_last_cell(self):
        from math import exp
        marginal, tail = poisson(12., cap=5)
        terms = [exp(-12.)]
        for k in range(1, 6): terms.append(terms[-1]*12./k)
        self.assertEqual(tail, 1.-fsum(terms))
        self.assertEqual(marginal, [p/fsum(terms) for p in terms])
        self.assertGreater(tail, .9)

    def test_actual_extreme_line_capture_and_decide_remain_pass_without_money(self):
        for goals in (None, 0, 1, 2):
            with self.subTest(goals=goals):
                case = example(NOW, 'numerical-'+str(goals))
                if goals is not None:
                    for row in case['sports']['history']:
                        row['home_goals'] = row['away_goals'] = goals
                repo = Repository(':memory:')
                try:
                    clock = [NOW]
                    service = Service(repo, clock=lambda: clock[0])
                    market = {'kind': 'TOTAL', 'side': 'UNDER', 'line': 1000.}
                    p = service.capture(case['sports'], [market])
                    self.assertEqual(p['coherence']['status'], 'UNSUPPORTED')
                    clock[0] = time(case['decision_at'])
                    q = {**case['quotes'][0], 'market': market}
                    result = service.decide(p['id'], [q], case['recheck'],
                                            {'bankroll': 1000., 'peak': 1000.}, case['decision_at'])
                    self.assertEqual((result['decision'], result['class'], result['risk']['stake']),
                                     ('PASS', 'D', 0.))
                    self.assertIn('CALIBRATION_COHERENCE_UNVERIFIED', [i['code'] for i in result['issues']])
                    self.assertEqual(repo.all('bets'), [])
                    self.assertEqual(repo.all('policy_approvals'), [])
                    self.assertTrue(repo.verify())
                finally:
                    repo.close()

    def test_changed_numerics_have_new_model_identity_and_same_policy(self):
        self.assertNotEqual(model_code_hash(), OLD_MODEL_HASH)
        self.assertEqual(Policy().fingerprint,
                         '5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9')

    def test_prior_calibrator_is_rejected_without_relabel_or_refit(self):
        case = example(NOW)
        artifact = {'version': CALIBRATION_SCHEMA, 'model_hash': OLD_MODEL_HASH,
                    'policy_hash': Policy().fingerprint,
                    'fit_at': (time(case['sports']['as_of'])-timedelta(seconds=1)).isoformat(),
                    'fit_ids': [], 'buckets': {}, 'synthetic': True, 'goal_model_hash': None}
        artifact['hash'] = digest(artifact)
        saved = copy.deepcopy(artifact)
        with self.assertRaisesRegex(ValueError, 'calibrator version/hash mismatch'):
            prepare(case['sports'], case['markets'], Policy(), artifact)
        self.assertEqual(artifact, saved)


if __name__ == '__main__': unittest.main()
