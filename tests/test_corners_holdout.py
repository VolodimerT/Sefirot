"""Synthetic temporal split contract checks; these are NOT empirical accuracy results."""
import unittest
from datetime import datetime,timezone,timedelta
from sefirot.corners_shadow import CornerMatch,Market
from sefirot.corners_holdout import score_frozen_split

UTC=timezone.utc
START=datetime(2025,1,1,12,tzinfo=UTC)
TEAMS=tuple("ABCDEFGHIJKL")

def rows(n=270):
    result=[]
    for i in range(n):
        h=TEAMS[i%12];a=TEAMS[(i+1+i//12)%12]
        if h==a:a=TEAMS[(i+2)%12]
        kickoff=START+timedelta(days=i)
        hf=2+(i*3)%8;af=1+(i*5)%7
        result.append(CornerMatch("synthetic-"+str(i),"TEST-CORNER",h,a,kickoff,
            kickoff+timedelta(hours=4),hf,af,hf//2,af//2,"synthetic-only"))
    return result

class TemporalSplitTests(unittest.TestCase):
    def test_scoring_no_money_and_baseline(self):
        report=score_frozen_split(rows(),league="TEST-CORNER",
            market=Market("FT","TOTAL","OVER",9.5),
            train_end=START+timedelta(days=154),
            evaluate_at=START+timedelta(days=271),
            min_team=6,minimum_evaluations=100)
        self.assertFalse(report["monetary_permission"])
        self.assertFalse(report["independent_holdout_verified"])
        self.assertEqual(report["status"],"RESEARCH_TEMPORAL_SPLIT")
        self.assertGreaterEqual(report["scored"],100)
        self.assertGreaterEqual(report["brier"],0)
        self.assertLessEqual(report["brier"],1)
        self.assertIn("benchmark_log_loss",report)

    def test_archive_known_later_cannot_backtest_earlier(self):
        data=rows()
        archive=datetime(2026,10,1,tzinfo=UTC)
        old=[CornerMatch(r.fixture_id,r.league,r.home,r.away,r.kickoff,archive,
                         r.home_ft,r.away_ft,r.home_1h,r.away_1h,r.source_id) for r in data]
        report=score_frozen_split(old,league="TEST-CORNER",
            market=Market("FT","TOTAL","OVER",9.5),
            train_end=START+timedelta(days=154),
            evaluate_at=START+timedelta(days=271),min_team=6)
        self.assertEqual(report["status"],"NO_TRAINING_BENCHMARK")

    def test_mixed_league_duplicate_fail_closed(self):
        data=rows(190)
        bad=CornerMatch("foreign","OTHER","A","B",START,
                        START+timedelta(hours=4),2,2,1,1,"synthetic")
        for wrong in [data+[data[0]],data+[bad]]:
            with self.assertRaisesRegex(ValueError,"duplicate|mixed league"):
                score_frozen_split(wrong,league="TEST-CORNER",
                     market=Market("FT","TOTAL","UNDER",9.5),
                     train_end=START+timedelta(days=100),
                     evaluate_at=START+timedelta(days=191))

    def test_asian_pushes_are_not_wins(self):
        report=score_frozen_split(rows(),league="TEST-CORNER",
            market=Market("FT","TEAM","AWAY_OVER",4.0),
            train_end=START+timedelta(days=154),
            evaluate_at=START+timedelta(days=271),
            min_team=6,minimum_evaluations=100)
        self.assertGreater(report["pushes"],0)
        self.assertEqual(report["scored"]+report["pushes"]+report["skipped"],
                         report["test_candidates"])

if __name__=="__main__":unittest.main()
