"""Verify parsing against all 66 observed public Match CSV header fields.

Rows are entirely synthetic; reproduces schema shape, NOT vendor data.
"""
import csv
from io import StringIO
import unittest
from research.provider_compare.footystats_csv import inspect_csv


REAL_HEADER = """timestamp,date_GMT,status,attendance,home_team_name,away_team_name,referee,Game Week,Pre-Match PPG (Home),Pre-Match PPG (Away),home_ppg,away_ppg,home_team_goal_count,away_team_goal_count,total_goal_count,total_goals_at_half_time,home_team_goal_count_half_time,away_team_goal_count_half_time,home_team_goal_timings,away_team_goal_timings,home_team_corner_count,away_team_corner_count,home_team_yellow_cards,home_team_red_cards,away_team_yellow_cards,away_team_red_cards,home_team_first_half_cards,home_team_second_half_cards,away_team_first_half_cards,away_team_second_half_cards,home_team_shots,away_team_shots,home_team_shots_on_target,away_team_shots_on_target,home_team_shots_off_target,away_team_shots_off_target,home_team_fouls,away_team_fouls,home_team_possession,away_team_possession,Home Team Pre-Match xG,Away Team Pre-Match xG,team_a_xg,team_b_xg,average_goals_per_match_pre_match,btts_percentage_pre_match,over_15_percentage_pre_match,over_25_percentage_pre_match,over_35_percentage_pre_match,over_45_percentage_pre_match,over_15_HT_FHG_percentage_pre_match,over_05_HT_FHG_percentage_pre_match,over_15_2HG_percentage_pre_match,over_05_2HG_percentage_pre_match,average_corners_per_match_pre_match,average_cards_per_match_pre_match,odds_ft_home_team_win,odds_ft_draw,odds_ft_away_team_win,odds_ft_over15,odds_ft_over25,odds_ft_over35,odds_ft_over45,odds_btts_yes,odds_btts_no,stadium_name""".split(",")


class ActualHeaderShapeTests(unittest.TestCase):
    def test_full_header_and_csv_quoted_fields(self):
        self.assertEqual(len(REAL_HEADER), 66)
        values = {k: "" for k in REAL_HEADER}
        values.update({
            "timestamp": "1533927600", "date_GMT": "Aug 10 2018 - 7:00pm",
            "status": "complete", "attendance": "123",
            "home_team_name": "Synthetic, Home", "away_team_name": "Synthetic Away",
            "home_team_goal_count": "2", "away_team_goal_count": "1",
            "total_goal_count": "3", "home_team_corner_count": "4",
            "away_team_corner_count": "5", "home_team_goal_timings": "3,83",
            "away_team_goal_timings": "90+2",
            "Pre-Match PPG (Home)": "2.00", "Home Team Pre-Match xG": "1.60",
            "team_a_xg": "1.30", "team_b_xg": "0.80",
            "odds_ft_home_team_win": "1.55",
            "stadium_name": "Test Park (Town, County)"
        })
        buf = StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=REAL_HEADER)
        writer.writeheader()
        writer.writerow(values)
        x = inspect_csv(buf.getvalue().encode("utf-8"), season="2018/2019", received_at="2026-10-11T04:00:00+00:00")
        self.assertEqual(x["count"], 1)
        self.assertEqual(x["records"][0]["goals"], [2, 1])
        self.assertEqual(x["records"][0]["corners"], [4, 5])
        self.assertTrue(x["has_prematch_columns"])
        self.assertTrue(x["has_1x2_odds_columns"])
        for banned in ("1.55", "1.60", "1.30", "2.00"):
            self.assertNotIn(banned, str(x["records"]))


if __name__ == "__main__":
    unittest.main()
