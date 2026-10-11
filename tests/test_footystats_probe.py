"""Synthetic-only tests for the external FootyStats offline research probe."""
import copy
import unittest
from research.provider_compare.footystats import inspect


AS_OF = "2026-10-11T00:00:00+00:00"


def page():
    return {"success": True, "pager": {"current_page": 1}, "data": [
        {"id": 111, "homeID": 41, "awayID": 42, "competition_id": 1625,
         "date_unix": 1537056000, "status": "complete", "homeGoalCount": 2,
         "awayGoalCount": 1, "team_a_corners": 5, "team_b_corners": 8,
         "odds_ft_1": 1.55, "pre_match_home_ppg": 1.89},
        {"id": 112, "homeID": 45, "awayID": 46,
         "date_unix": 1830000000, "status": "incomplete"}
    ]}


class FootyStatsProbeTests(unittest.TestCase):
    def probe(self, doc=None):
        return inspect(page() if doc is None else doc, season_id=1625, received_at=AS_OF)

    def test_enumeration_and_coverage(self):
        r = self.probe()
        self.assertEqual(r["fixture_count"], 2)
        self.assertEqual(r["coverage"]["complete_goal_scores"], 1)
        self.assertEqual(r["coverage"]["complete_corner_scores"], 1)
        self.assertEqual(r["records"][0]["corners"], [5, 8])
        self.assertEqual(r["records"][0]["source_match_id"], "footystats:match:111")

    def test_never_promotes_historical(self):
        r = self.probe()
        self.assertFalse(r["training_allowed"])
        self.assertFalse(r["prospective_holdout_allowed"])
        self.assertFalse(r["monetary_permission"])
        self.assertIsNone(r["records"][0]["original_publication_time"])
        self.assertEqual(r["records"][0]["first_observed_at"], AS_OF)
        self.assertNotIn("odds_ft_1", r["records"][0])
        self.assertNotIn("pre_match_home_ppg", r["records"][0])

    def test_fails_duplicate(self):
        d = page()
        d["data"].append(copy.deepcopy(d["data"][0]))
        with self.assertRaises(ValueError):
            self.probe(d)

    def test_fails_wrong_season(self):
        d = page()
        d["data"][0]["competition_id"] = 123
        with self.assertRaises(ValueError):
            self.probe(d)

    def test_fails_partial_corners(self):
        d = page()
        d["data"][0]["team_b_corners"] = None
        with self.assertRaises(ValueError):
            self.probe(d)

    def test_absent_corners_is_not_zero(self):
        d = page()
        d["data"][0].pop("team_b_corners")
        d["data"][0].pop("team_a_corners")
        r = self.probe(d)
        self.assertEqual(r["coverage"]["complete_corner_scores"], 0)
        self.assertIsNone(r["records"][0]["corners"])

    def test_fails_future_finished(self):
        d = page()
        d["data"][0]["date_unix"] = 1830000000
        with self.assertRaises(ValueError):
            self.probe(d)

    def test_fails_missing_tz(self):
        with self.assertRaises(ValueError):
            inspect(page(), season_id=1625, received_at="2026-10-11T00:00:00")

    def test_fails_bad_pagination(self):
        with self.assertRaises(ValueError):
            inspect(page(), season_id=1625, received_at=AS_OF, expected_page=2)

    def test_fails_unsigned_negative_or_float_counts(self):
        for value in (-1, 3.5, "3", True):
            d = page()
            d["data"][0]["homeGoalCount"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.probe(d)

    def test_input_not_mutated(self):
        d = page()
        original = copy.deepcopy(d)
        self.probe(d)
        self.assertEqual(d, original)

    def test_nonsuccess_is_not_success(self):
        with self.assertRaises(ValueError):
            self.probe({"success": False, "data": []})


if __name__ == "__main__":
    unittest.main()
