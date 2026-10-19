"""Synthetic count-period regressions and strict no-source public matrix."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from sefirot.corners_shadow import CornerMatch,CornerForecast,Market,walk_forward,fit,price,period_counts
from sefirot.corners_holdout import _observed
from research.small_family_shadow import family_report
from test_corners_shadow import rows,predict,START
from test_small_observation_v2 import sample,AT

class CornerIntegrationTests(unittest.TestCase):
    def test_half_double_chance_walk_forward_uses_half_result_not_ft(self):
        data=[CornerMatch("synthetic-"+str(i),"SYNTHETIC","A","B",
            START+timedelta(days=i),START+timedelta(days=i,hours=2),5,2,0,2,"SYNTHETIC") for i in range(12)]
        def controlled(*args,**kw):return CornerForecast("SYNTHETIC","A","B",kw["as_of"],
            5.,2.,.1,2.,None,None,10,10,10,("SYNTHETIC",),"0"*64)
        with patch("sefirot.corners_shadow.fit",side_effect=controlled):
            out=walk_forward(data,Market("1H","DOUBLE_CHANCE","1X"),
                             league="SYNTHETIC",min_league=10,min_team=1)
        self.assertEqual(out["scored"],2)
        self.assertEqual(out["realized_rate"],0.)
        self.assertFalse(out["independent_holdout_complete"])

    def test_second_half_counts_come_from_same_corner_row_not_goal_rates(self):
        row=CornerMatch("synthetic","SYNTHETIC","A","B",START,START+timedelta(hours=2),8,5,3,2,"SYNTHETIC")
        self.assertEqual(period_counts(row,"2H"),(5,3))
        self.assertEqual(_observed(row,Market("2H","TEAM","HOME_OVER",5)),(None,True))
        f=predict()
        out=price(f,Market("2H","TOTAL","OVER",4),2.)
        self.assertGreater(out["push"],0)
        self.assertAlmostEqual(out["win"]+out["push"]+out["loss"],1.,places=7)
        self.assertFalse(out["monetary_permission"])

    def test_no_source_matrix_has_no_parameters_p_ev_or_combined_price(self):
        out=family_report("CORNERS",at=AT)
        self.assertEqual(len(out["matrix"]),9)
        self.assertEqual({r["period"] for r in out["matrix"]},{"FT","1H","2H"})
        for row in out["matrix"]:
            self.assertIsNone(row["eligible_denominator"])
            self.assertIsNone(row["model_parameters"])
            self.assertIsNone(row["probability"]);self.assertIsNone(row["ev"])
        self.assertIsNone(out["builder"]["joint_probability"])
        self.assertFalse(out["builder"]["marginal_product_used"])
        self.assertEqual(out["stake"],0)

    def test_full_manifest_and_zero_counts_still_do_not_attest_origin_or_calibration(self):
        data=sample();out=family_report("CORNERS",data=data,at=AT)
        ft=next(r for r in out["matrix"] if r["period"]=="FT" and r["scope"]=="MATCH")
        self.assertEqual(ft["known_fixtures"],2)
        self.assertEqual(ft["observed_coverage"],1.)
        self.assertIsNone(ft["probability"]);self.assertFalse(ft["fit_allowed"])

    def test_missing_counts_and_revision_conflict_reuse_original_qc(self):
        data=sample();data["observations"][0]["counts"]["FT"]["CORNERS"]["away"]=None
        out=family_report("CORNERS",data=data,at=AT)
        self.assertEqual(next(r for r in out["matrix"] if r["period"]=="FT")["missing_fixtures"],1)
        self.assertTrue(all(r["probability"] is None for r in out["matrix"]))

    def test_caller_origin_flag_is_not_a_source_certificate(self):
        data=sample();data["source_attested"]=True
        with self.assertRaises(ValueError):family_report("CORNERS",data=data,at=AT)

    def test_unknown_family_does_not_borrow_corner_model(self):
        with self.assertRaises(ValueError):family_report("GOALS",at=AT)
