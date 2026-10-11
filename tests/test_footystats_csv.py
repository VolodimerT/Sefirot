"""FootyStats Premium Match CSV adapter: adversarial, synthetic CSV tests.

Header intentionally matches fields seen in the official public EPL 2018/19
sample, but test data are fabricated and never certified observations.
"""
import csv
from io import StringIO
import unittest
from research.provider_compare.footystats_csv import inspect_csv, MAX_CSV_BYTES

HEADER = [
    "timestamp", "date_GMT", "status", "home_team_name", "away_team_name",
    "home_team_goal_count", "away_team_goal_count", "total_goal_count",
    "home_team_corner_count", "away_team_corner_count",
    "Pre-Match PPG (Home)", "Pre-Match PPG (Away)", "home_ppg", "team_a_xg",
    "odds_ft_home_team_win", "odds_ft_draw", "odds_ft_away_team_win"
]
ASOF = "2026-10-11T04:00:00+00:00"


def make_doc(rows=None):
    rows = rows if rows is not None else [
        ["1533927600", "Aug 10 2018 - 7:00pm", "complete", "Sample United", "Sample City", "2", "1", "3", "2", "5", "0", "0", "2.9", "1.12", "1.37", "4.98", "9.81"],
        ["1533987000", "Aug 11 2018 - 11:30am", "complete", "Sample Town", "Sample Wanderers", "1", "2", "3", "3", "5", "1.5", "1.2", "1.8", "1.05", "4.51", "3.77", "1.84"]
    ]
    buf = StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


class CsvTrialTests(unittest.TestCase):
    def read(self, doc=None, **kw):
        return inspect_csv(make_doc() if doc is None else doc,
                           season="2018/2019", received_at=ASOF, **kw)

    def test_coverage_and_identity(self):
        x = self.read(expected_matches=2)
        self.assertEqual(x["count"], 2)
        self.assertEqual(x["coverage"]["complete_goal_scores"], 2)
        self.assertEqual(x["coverage"]["complete_corner_scores"], 2)
        self.assertNotEqual(x["records"][0]["local_candidate_id"],
                            x["records"][1]["local_candidate_id"])
        self.assertIsNone(x["records"][0]["original_fixture_id"])
        self.assertEqual(x["records"][0]["corners"], [2, 5])

    def test_research_only_even_prematch_named_features(self):
        x = self.read()
        self.assertEqual(x["status"], "KEEP_SHADOW")
        self.assertFalse(x["training_allowed"])
        self.assertFalse(x["holdout_allowed"])
        self.assertFalse(x["monetary_permission"])
        self.assertTrue(x["has_prematch_columns"])
        self.assertTrue(x["has_1x2_odds_columns"])
        self.assertNotIn("home_ppg", str(x["records"]))
        self.assertNotIn("odds_ft_", str(x["records"]))
        self.assertEqual(x["records"][0]["prematch_feature_availability"], "UNVERIFIED")

    def test_duplicate(self):
        one = make_doc().decode().splitlines()
        with self.assertRaises(ValueError):
            self.read(("\n".join(one + [one[1]]) + "\n").encode())

    def test_wrong_goal_sum(self):
        s = make_doc().decode().replace("2,1,3,2,5", "2,1,9,2,5")
        with self.assertRaises(ValueError):
            self.read(s.encode())

    def test_partial_corner_count(self):
        s = make_doc().decode().replace(",3,2,5,", ",3,2,,")
        with self.assertRaises(ValueError):
            self.read(s.encode())

    def test_both_missing_corners_is_not_zero(self):
        s = make_doc().decode().replace(",3,2,5,", ",3,,,")
        x = self.read(s.encode())
        self.assertEqual(x["coverage"]["complete_corner_scores"], 1)
        self.assertIsNone(x["records"][0]["corners"])

    def test_future_complete(self):
        s = make_doc().decode().replace("1533927600", "1833927600")
        with self.assertRaises(ValueError):
            self.read(s.encode())

    def test_bad_timezone(self):
        with self.assertRaises(ValueError):
            inspect_csv(make_doc(), season="2018/2019", received_at="2026-10-11")

    def test_wrong_status(self):
        s = make_doc().decode().replace(",complete,", ",FT,", 1)
        with self.assertRaises(ValueError):
            self.read(s.encode())

    def test_duplicated_headers(self):
        s = make_doc().decode().replace("away_team_name,", "home_team_name,", 1)
        with self.assertRaises(ValueError):
            self.read(s.encode())

    def test_wrong_row_column_count(self):
        with self.assertRaises(ValueError):
            self.read(make_doc() + b",EXTRA\n")

    def test_bad_integer_counts(self):
        for bad in ("-1", "NaN", "0.5", "999999999"):
            s = make_doc().decode().replace(",2,1,3,2,5,", "," + bad + ",1,3,2,5,", 1)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.read(s.encode())

    def test_not_match_csv_header(self):
        with self.assertRaises(ValueError):
            self.read(b"timestamp,status\n1,complete\n")

    def test_bom_csv(self):
        x = self.read(b"\xef\xbb\xbf" + make_doc())
        self.assertEqual(x["count"], 2)

    def test_oversized_csv(self):
        with self.assertRaises(ValueError):
            self.read(b"x" * (MAX_CSV_BYTES + 1))

    def test_csv_quoted_team_name(self):
        s = make_doc().decode().replace("Sample United", '"Example, United"')
        x = self.read(s.encode())
        self.assertEqual(x["count"], 2)

    def test_observed_at_is_not_match_date(self):
        x = self.read()
        self.assertEqual(x["records"][0]["observed_at"], ASOF)
        self.assertTrue(x["records"][0]["kickoff_utc"].startswith("2018-"))
        self.assertIsNone(x["records"][0]["original_fixture_id"])

    def test_blank_goals_remain_unknown(self):
        s = make_doc().decode().replace(",2,1,3,2,5,", ",,,3,2,5,", 1)
        x = self.read(s.encode())
        self.assertEqual(x["coverage"]["complete_goal_scores"], 1)
        self.assertIsNone(x["records"][0]["goals"])

    def test_expected_count_mismatch(self):
        with self.assertRaises(ValueError):
            self.read(expected_matches=380)


if __name__ == "__main__":
    unittest.main()
