import unittest
from test_arena_diagnostic import OriginalFixture
from research.football_intelligence_v7.score_review import score_original
from research.football_intelligence_v7.mobile_preview import render


class ResearchScoreTests(OriginalFixture, unittest.TestCase):
    def test_roles_preserve_original_probability_and_blockers(self):
        review = score_original(self.prediction, self.case['quotes'], self.at)
        self.assertEqual(len(review['roles']), 8)
        self.assertIsNone(review['consensus'])
        self.assertFalse(review['monetary_permission'])
        self.assertEqual([v['original_base'] for v in review['blockers']],
                         [v['base'] for v in self.prediction['candidates']])

    def test_reconstructed_seal_refused(self):
        changed = self.changed(lambda p:p.update(reconstructed=True))
        with self.assertRaises(ValueError):
            score_original(changed, [], self.at)

    def test_preview_escapes_untrusted_names(self):
        page = render(dict(as_of='UTC',matches=[dict(teams=dict(home='<script>',away='Team'),
            kickoff='UTC',probabilities={'Poisson':[.3,.4,.3]},scores={'market_fit':None},reasons=[])]))
        self.assertNotIn('<script>',page)
        self.assertIn('PASS',page)
        self.assertIn('30.0%',page)
