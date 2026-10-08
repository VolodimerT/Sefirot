"""Data-session history triage: no fabricated API data or retrospective seals."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sefirot.contracts import digest
from scripts.calibration_history_triage import analyze


def report():
    x = {
        "schema": "api-data-session-v1", "started_at": "2026-10-08T09:00:00+00:00",
        "day": "2026-10-08", "output_directory": "/tmp/unique-archive",
        "blockers": ["PROVIDER_ACCOUNT_SUSPENDED"],
        "fixtures": [{
            "match_id": "M1", "status": "INSUFFICIENT_HISTORY",
            "coverage": {
                "match": {"kickoff": "2026-10-08T20:00:00+00:00", "league": "E0"},
                "teams": {
                    "home": {"name": "A", "eligible_games": 2, "games_needed": 6},
                    "away": {"name": "B", "eligible_games": 5, "games_needed": 3},
                },
                "blockers": ["INSUFFICIENT_HISTORY"],
                "observed_history_seasons": {"2026": 8},
                "exclusion_reasons": {"NOT_REGULATION_FT": 5},
            },
        }],
        "monetary_permission": False, "execution_enabled": False,
    }
    x["hash"] = digest(x)
    return x


class HistoryTriageTests(unittest.TestCase):
    def test_actual_missing_team_games_and_provider(self):
        r=analyze([report()])
        self.assertEqual(r["insufficient_history_fixtures"],1)
        self.assertEqual(r["missing_team_games"][0]["deficits"]["home"]["missing_games"],6)
        self.assertEqual(r["action"],"RECOVER_PROVIDER_ACCESS_FIRST")
        self.assertEqual(r["api_calls"],0)
        self.assertFalse(r["forecast_backfilled"])
        self.assertFalse(r["monetary_permission"])

    def test_tampered_source_rejected(self):
        x=report();x["fixtures"][0]["coverage"]["teams"]["home"]["games_needed"]=0
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            analyze([x])

    def test_duplicate_session_is_not_new_data(self):
        with self.assertRaisesRegex(ValueError,"twice"):
            analyze([report(),report()])

    def test_same_match_two_sessions_not_twice_a_new_observation(self):
        a=report();b=copy.deepcopy(a)
        b["started_at"]="2026-10-08T11:00:00+00:00"
        b["output_directory"]="/tmp/other"
        b["hash"]=digest({k:v for k,v in b.items() if k!="hash"})
        result=analyze([a,b])
        self.assertEqual(result["unique_fixtures"],1)
        self.assertTrue(result["missing_team_games"][0]["seen_in_multiple_sessions"])
        self.assertEqual(result["insufficient_history_fixtures"],1)

    def test_unsafe_session_rejected(self):
        x=report();x["monetary_permission"]=True
        x["hash"]=digest({k:v for k,v in x.items() if k!="hash"})
        with self.assertRaisesRegex(ValueError,"research-only"):
            analyze([x])

if __name__=="__main__":
    unittest.main()
