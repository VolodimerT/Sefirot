"""Synthetic paired-count support and original source/QC gate reuse."""
from pathlib import Path
import sys
import unittest
from math import fsum
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from research.shots_shadow import parameters_from_paired_counts,count_joint
from research.small_family_shadow import family_report
from test_small_observation_v2 import sample,AT

def rows():
    return [{"fixture_id":"synthetic-"+str(i),"shots":3,"sot":1} for i in range(20)]

class ShotsShadowTests(unittest.TestCase):
    def test_paired_own_counts_and_joint_support_sot_never_exceeds_shots(self):
        p=parameters_from_paired_counts(rows())
        self.assertEqual(p["shots_mean"],3.)
        self.assertEqual(p["sot_given_shot"],1/3)
        mass=count_joint(p["shots_mean"],p["sot_given_shot"])
        self.assertTrue(all(sot<=shots for shots,sot in mass))
        self.assertAlmostEqual(fsum(mass.values()),1.,places=10)
        self.assertAlmostEqual(fsum(sot*v for (shots,sot),v in mass.items()),1.,places=9)
        self.assertFalse(p["source_attested"])

    def test_missing_bool_duplicate_and_sot_contradiction_cannot_fit_lab(self):
        for field,value in (("shots",None),("sot",True),("sot",4)):
            data=rows();data[0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                parameters_from_paired_counts(data)
        data=rows();data[-1]["fixture_id"]=data[0]["fixture_id"]
        with self.assertRaises(ValueError):parameters_from_paired_counts(data)

    def test_zero_observations_are_known_but_do_not_invent_a_thinning_rate(self):
        data=[{"fixture_id":"synthetic-"+str(i),"shots":0,"sot":0} for i in range(20)]
        p=parameters_from_paired_counts(data)
        self.assertEqual(p["shots_mean"],0.)
        self.assertIsNone(p["sot_given_shot"])
        with self.assertRaises(ValueError):count_joint(p["shots_mean"],p["sot_given_shot"])

    def test_no_archive_has_null_p_ev_and_independent_model_for_both_metrics(self):
        out=family_report("SHOTS_SOT",at=AT)
        self.assertEqual(len(out["matrix"]),18)
        self.assertEqual({r["metric"] for r in out["matrix"]},{"SHOTS","SOT"})
        self.assertTrue(all(r["probability"] is None and r["ev"] is None and
            r["model_parameters"] is None for r in out["matrix"]))
        self.assertIsNone(out["builder"]["joint_probability"])
        self.assertEqual(out["stake"],0)

    def test_original_qc_quarantines_sot_exceeds_shots_without_surrogate_probability(self):
        data=sample();data["observations"][0]["counts"]["FT"]["SOT"]["home"]=1
        out=family_report("SHOTS_SOT",data=data,at=AT)
        self.assertTrue(any("SOURCE_QUARANTINE" in r["blockers"] for r in out["matrix"]))
        self.assertTrue(all(r["probability"] is None for r in out["matrix"]))

    def test_goals_or_unknown_fields_cannot_substitute_shot_inputs(self):
        data=rows();data[0]["goal_lambda"]=1.5
        with self.assertRaises(ValueError):parameters_from_paired_counts(data)
        with self.assertRaises(ValueError):count_joint(True,.3)
