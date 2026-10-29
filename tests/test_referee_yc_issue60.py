"""Synthetic prerequisite attacks; no real referee proof/probability/EV."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from research.referee_yc_shadow import inspect_referee,own_yc_count_parameters,REQUIREMENTS
from research.small_family_shadow import family_report
from test_small_observation_v2 import sample,AT

def declared():
    return {"fixture_id":"synthetic-f","kickoff":"2030-01-01T12:00:00+00:00",
        "referee_id":"synthetic-r","confirmed_at":"2030-01-01T10:00:00+00:00",
        "yc_per_game":4.,"yc_per_foul":.2,"risk":.3,"rules_version":"synthetic-only",
        "cleaner_market_exists":False,"calibration_hash":"a"*64,"ev":.1}

class RefereeYCGateTests(unittest.TestCase):
    def test_each_missing_prerequisite_holds_without_surrogate_probability(self):
        for key,reason in REQUIREMENTS.items():
            value=declared();value[key]=None;r=inspect_referee(value)
            with self.subTest(key=key):
                self.assertIn(reason,r["blockers"])
                self.assertEqual((r["decision"],r["class"],r["stake"]),("PASS","D",0.))
                self.assertIsNone(r["probability"]);self.assertIsNone(r["ev"])

    def test_complete_caller_shape_and_fake_source_verified_cannot_pass(self):
        r=inspect_referee(declared())
        self.assertIn("INDEPENDENT_REFEREE_SOURCE_ORIGIN_NOT_ATTESTED",r["blockers"])
        self.assertEqual(r["status"],"HOLD")
        value=declared();value["source_verified"]=True
        self.assertIn("CALLER_ATTESTATION_OR_UNKNOWN_FIELDS_REJECTED",inspect_referee(value)["blockers"])

    def test_risk_bool_nonfinite_out_of_range_negative_rates_and_ev_refuse(self):
        for key,value,reason in (("risk",True,"INVALID_REFEREE_NUMBER"),
            ("risk",float("nan"),"INVALID_REFEREE_NUMBER"),("risk",1.1,"RISK_OUTSIDE_0_1"),
            ("yc_per_game",-1,"NEGATIVE_REFEREE_RATE"),("ev",0,"NO_VERIFIED_POSITIVE_EV")):
            context=declared();context[key]=value
            self.assertIn(reason,inspect_referee(context)["blockers"])

    def test_late_referee_cleaner_market_or_wrong_rules_reference_holds(self):
        value=declared();value["confirmed_at"]=value["kickoff"]
        self.assertIn("REFEREE_NOT_CONFIRMED_PREMATCH",inspect_referee(value)["blockers"])
        value=declared();value["cleaner_market_exists"]=True
        self.assertIn("CLEANER_MAIN_MARKET_EXISTS",inspect_referee(value)["blockers"])
        value=declared();value["rules_version"]=""
        self.assertIn("INVALID_REFEREE_ID_OR_RULES",inspect_referee(value)["blockers"])
        value=declared();value["calibration_hash"]="caller assertion"
        self.assertIn("INVALID_CALIBRATION_CONTENT_REFERENCE",inspect_referee(value)["blockers"])

    def test_own_yc_counts_never_use_fouls_or_mix_referee_identity(self):
        rows=[{"fixture_id":"synthetic-"+str(i),"referee_id":"synthetic-r","yc":4} for i in range(20)]
        r=own_yc_count_parameters(rows);self.assertEqual(r["own_yc_mean"],4.)
        self.assertFalse(r["referee_gate_passed"]);self.assertIsNone(r["probability"])
        rows[0]["fouls"]=20
        with self.assertRaises(ValueError):own_yc_count_parameters(rows)
        rows[0].pop("fouls");rows[0]["referee_id"]="other"
        with self.assertRaises(ValueError):own_yc_count_parameters(rows)

    def test_matrix_uses_original_qc_referee_missing_and_all_public_numbers_null(self):
        for data in (None,sample()):
            r=family_report("YC",data=data,at=AT)
            self.assertEqual(len(r["matrix"]),9)
            self.assertEqual(r["referee_gate"]["status"],"HOLD")
            self.assertTrue(all(x["probability"] is None and x["ev"] is None and
                x["model_parameters"] is None and "REFEREE_GATE_HOLD" in x["blockers"] for x in r["matrix"]))
            self.assertFalse(r["builder"]["marginal_product_used"])
            self.assertEqual(r["stake"],0)
