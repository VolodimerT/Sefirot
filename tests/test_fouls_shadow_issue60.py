"""Synthetic direct-direction counts, existing QC and no false YC/source."""
from pathlib import Path
from math import fsum
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from research.fouls_shadow import parameters_from_direct_counts,count_mass
from research.small_family_shadow import family_report
from test_small_observation_v2 import sample,AT

def rows():return [{"fixture_id":"synthetic-"+str(i),"committed":10,"suffered":7,"style":None} for i in range(20)]

class FoulShadowTests(unittest.TestCase):
    def test_direct_directions_stay_separate_and_no_yellow_card_surrogate(self):
        p=parameters_from_direct_counts(rows())
        self.assertEqual(p["committed_mean"],10.)
        self.assertEqual(p["suffered_mean"],7.)
        self.assertIsNone(p["yellow_card_probability"])
        self.assertFalse(p["source_attested"])
        self.assertAlmostEqual(fsum(i*x for i,x in enumerate(count_mass(p["committed_mean"]))),10.,places=9)

    def test_missing_suffered_not_zero_or_other_team_proxy(self):
        data=rows();data[0]["suffered"]=None
        with self.assertRaisesRegex(ValueError,"MISSING_IS_NOT_ZERO"):parameters_from_direct_counts(data)
        data=rows();data[0]["yellow_cards"]=1
        with self.assertRaises(ValueError):parameters_from_direct_counts(data)

    def test_duplicate_bool_and_unattested_style_cannot_create_admission(self):
        data=rows();data[-1]["fixture_id"]=data[0]["fixture_id"]
        with self.assertRaises(ValueError):parameters_from_direct_counts(data)
        data=rows();data[0]["committed"]=True
        with self.assertRaises(ValueError):parameters_from_direct_counts(data)
        data=rows();data[0]["style"]="DIRECT_CALLER_DESCRIPTION"
        self.assertIn("NOT_INDEPENDENTLY_ATTESTED",parameters_from_direct_counts(data)["style_status"])

    def test_no_source_direction_matrix_null_and_no_bookmaker_builder_price(self):
        r=family_report("FOULS",at=AT)
        self.assertEqual(len(r["matrix"]),18)
        self.assertEqual({m["metric"] for m in r["matrix"]},{"FOULS_COMMITTED","FOULS_SUFFERED"})
        self.assertTrue(all(m["probability"] is None and m["ev"] is None for m in r["matrix"]))
        self.assertIsNone(r["builder"]["combined_bookmaker_quote"])

    def test_existing_v2_batch_still_valid_but_no_suffered_definition_is_invented(self):
        r=family_report("FOULS",data=sample(),at=AT)
        committed=next(m for m in r["matrix"] if m["metric"]=="FOULS_COMMITTED" and m["period"]=="FT")
        suffered=next(m for m in r["matrix"] if m["metric"]=="FOULS_SUFFERED" and m["period"]=="FT")
        self.assertEqual(committed["known_fixtures"],2)
        self.assertEqual(suffered["eligible_denominator"],2)
        self.assertEqual(suffered["missing_fixtures"],2)
        self.assertIsNone(suffered["probability"])
        self.assertIn("DIRECT_METRIC_NOT_AVAILABLE_IN_OBSERVATION_V2",suffered["blockers"])
