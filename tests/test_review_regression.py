"""Independent offline QA against the exact PR #77 source."""
import unittest
from test_audit_upgrade import controlled, decision
from sefirot.quarter_lines import simulate_express


class MissingReleaseRegression(unittest.TestCase):
    def test_missing_holdout_returns_pass_instead_of_raising(self):
        for release in ('absent', None, {'passed': False}):
            with self.subTest(release=release):
                prediction, case, quotes, context = controlled(win=.48, odds=2.)
                key = prediction['candidates'][0]['key']
                if release == 'absent':
                    context['releases'].pop(key)
                else:
                    context['releases'][key] = release
                result = decision(prediction, case, quotes, context)
                self.assertEqual(result['decision'], 'PASS')
                self.assertEqual(result['class'], 'C')
                self.assertEqual(result['risk']['stake'], 0.)
                self.assertIn('HOLDOUT_UNVALIDATED', result['limiting_factors'])


class MixedExpressRegression(unittest.TestCase):
    def test_quarter_integer_and_result_legs_handle_half_loss_and_push(self):
        legs = [
            {'fixture_id': 'marseille', 'kind': 'TEAM_TOTAL', 'side': 'AWAY_OVER',
             'line': 1.25, 'home': 0, 'away': 1, 'odds': 1.9},
            {'fixture_id': 'fiorentina', 'kind': 'TEAM_TOTAL', 'side': 'HOME_OVER',
             'line': 1., 'home': 1, 'away': 0, 'odds': 1.77},
            {'fixture_id': 'barcelona', 'kind': '1X2', 'side': 'AWAY',
             'home': 1, 'away': 2, 'odds': 1.87},
        ]
        result = simulate_express(legs, 500., 500.)
        self.assertAlmostEqual(result['gross_return'], 467.5)
        self.assertAlmostEqual(result['net_result'], -32.5)
        self.assertEqual(result['decision'], 'PASS')
        self.assertFalse(result['monetary_permission'])
        legs[1]['home'] = 2
        self.assertAlmostEqual(simulate_express(legs, 500., 500.)['gross_return'], 827.475)
        legs[2]['away'] = 1
        self.assertEqual(simulate_express(legs, 500., 500.)['gross_return'], 0.)

    def test_mixed_dnb_draw_quarter_under_and_half_total(self):
        legs = [
            {'fixture_id': 'first', 'kind': 'DNB', 'side': 'AWAY',
             'home': 1, 'away': 1, 'odds': 1.46},
            {'fixture_id': 'second', 'kind': 'TOTAL', 'side': 'UNDER',
             'line': 1.75, 'home': 1, 'away': 1, 'odds': 2.},
            {'fixture_id': 'third', 'kind': 'TOTAL', 'side': 'OVER',
             'line': 1.5, 'home': 2, 'away': 1, 'odds': 1.5},
        ]
        self.assertAlmostEqual(simulate_express(legs, 100., 100.)['gross_return'], 75.)
        legs[2]['fixture_id'] = 'first'
        with self.assertRaisesRegex(ValueError, 'joint builder'):
            simulate_express(legs, 100., 100.)


if __name__ == '__main__':
    unittest.main()
