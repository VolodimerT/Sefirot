"""Synthetic-only tests: NEVER interpret these as model accuracy validation."""
import math
import unittest
from datetime import datetime,timedelta,timezone
from sefirot.corners_shadow import CornerMatch,Market,fit,price,walk_forward,STATUS

UTC=timezone.utc
START=datetime(2026,1,1,12,tzinfo=UTC)

def rows(n=180,*,future=False):
    teams=tuple("ABCDEFGHIJKL")
    out=[]
    for i in range(n):
        h=teams[i%12]
        a=teams[(i+1+i//12)%12]
        if h==a:a=teams[(i+2)%12]
        hc=2+(i*3)%8
        ac=1+(i*7)%7
        t=START+timedelta(days=i)
        out.append(CornerMatch(f"fixture-{i}","COL-PRIMERA-A",h,a,t,
                               t+timedelta(hours=4),hc,ac,hc//2,ac//2,"verified-archive"))
    if future:
        r=out[-1]
        out[-1]=CornerMatch(r.fixture_id,r.league,r.home,r.away,r.kickoff,
                            START+timedelta(days=n+15),r.home_ft,r.away_ft,
                            r.home_1h,r.away_1h,r.source_id)
    return out

def predict(data=None):
    return fit(rows() if data is None else data,league="COL-PRIMERA-A",
               home="A",away="B",as_of=START+timedelta(days=185),kickoff=START+timedelta(days=186),min_league=80,min_team=8)

class CornerShadowContract(unittest.TestCase):
    def test_future_and_availability_leakage(self):
        with self.assertRaisesRegex(ValueError,"future/unavailable"):
            predict(rows(future=True))
        with self.assertRaisesRegex(ValueError,"result availability"):
            CornerMatch("bad","COL-PRIMERA-A","A","B",START,START,4,5,2,3,"x")
        with self.assertRaisesRegex(ValueError,"not prematch"):
            fit(rows(),league="COL-PRIMERA-A",home="A",away="B",as_of=START+timedelta(days=185),kickoff=START+timedelta(days=184))
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            CornerMatch("bad","COL-PRIMERA-A","A","B",START.replace(tzinfo=None),
                        START+timedelta(hours=4),4,5,2,3,"x")

    def test_duplicates_mixed_competition_and_half(self):
        r=rows()
        with self.assertRaisesRegex(ValueError,"duplicate"):
            predict(r+[r[0]])
        with self.assertRaisesRegex(ValueError,"mixed competitions"):
            predict(r+[CornerMatch("other","CHL-PRIMERA","X","Y",START,
                                    START+timedelta(hours=4),3,4,1,2,"src")])
        with self.assertRaisesRegex(ValueError,"first-half"):
            CornerMatch("bad","COL-PRIMERA-A","A","B",START,
                        START+timedelta(hours=4),1,5,2,3,"src")
        with self.assertRaisesRegex(ValueError,"verified corner count"):
            CornerMatch("bad","COL-PRIMERA-A","A","B",START,
                        START+timedelta(hours=4),True,5,0,3,"src")

    def test_fail_closed_insufficient_data(self):
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT_LEAGUE_COVERAGE|INSUFFICIENT_HISTORY"):
            predict(rows(25))
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT_HISTORY"):
            fit(rows(80),league="COL-PRIMERA-A",home="Z",away="B",
                as_of=START+timedelta(days=185),kickoff=START+timedelta(days=186))

    def test_shadow_has_no_bet_permission(self):
        f=predict()
        self.assertEqual(f.status,STATUS)
        self.assertFalse(f.monetary_permission)
        self.assertGreater(f.matches,100)
        self.assertEqual(f.history_sha256,predict().history_sha256)
        self.assertGreater(f.full_home,0)
        self.assertLess(f.half_home,f.full_home+2)

    def test_asian_push_and_half_time_only(self):
        f=predict()
        x=price(f,Market("FT","TEAM","AWAY_OVER",4.0),2.04)
        self.assertGreater(x["push"],0)
        self.assertAlmostEqual(x["win"]+x["push"]+x["loss"],1.,places=7)
        self.assertAlmostEqual(x["fair_odds"],(1-x["push"])/x["win"])
        self.assertFalse(x["monetary_permission"])
        y=price(f,Market("1H","TOTAL","UNDER",4.5),1.90)
        self.assertEqual(y["push"],0)
        self.assertLessEqual(y["stress_ev_min"],y["raw_ev"])
        self.assertGreaterEqual(y["stress_ev_max"],y["raw_ev"])

    def test_corners_double_chance_not_goals(self):
        f=predict()
        p=[price(f,Market("FT","DOUBLE_CHANCE",side),1.50) for side in ("1X","X2")]
        self.assertGreater(p[0]["win"]+p[1]["win"]-1,0)
        self.assertEqual(p[0]["push"],0)
        self.assertFalse(p[1]["monetary_permission"])

    def test_reject_incompatible_contracts(self):
        invalid=[lambda:Market("FT","TOTAL","OVER",9.25),
                 lambda:Market("FT","GOALS","OVER",2.5),
                 lambda:Market("2H","TOTAL","OVER",2.5),
                 lambda:Market("FT","DOUBLE_CHANCE","1X",0.5)]
        for f in invalid:
            with self.assertRaises(ValueError): f()

    def test_walk_forward_research_not_independent_holdout(self):
        r=walk_forward(rows(190),Market("FT","TOTAL","OVER",9.5),
                       league="COL-PRIMERA-A",min_league=70,min_team=4)
        self.assertIn(r["status"],("INSUFFICIENT_HOLDOUT","RESEARCH_WALK_FORWARD_ONLY"))
        if r["scored"]:
            self.assertTrue(0<=r["brier"]<=1)
            self.assertTrue(math.isfinite(r["logloss"]))
            self.assertEqual(len(r["evaluated_ids"]),len(set(r["evaluated_ids"])))
            self.assertFalse(r["independent_holdout_complete"])

    def test_stress_is_uncertainty_not_signal(self):
        f=predict()
        v=price(f,Market("FT","TOTAL","UNDER",9.5),1.98)
        self.assertGreater(v["win"],0)
        self.assertLess(v["win"],1)
        self.assertLess(v["stress_ev_min"],v["stress_ev_max"])
        self.assertFalse(v["monetary_permission"])

if __name__=="__main__":
    unittest.main()
