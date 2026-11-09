"""Independent offline QA against the exact PR #77 source."""
import unittest
from test_audit_upgrade import controlled, decision


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


if __name__ == '__main__':
    unittest.main()
