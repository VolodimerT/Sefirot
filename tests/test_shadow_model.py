"""Offline tests: true SEFIROT engine adapter stays research-only and respects kickoff."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from research import shadow_model as shadow

NOW = datetime.now(timezone.utc).replace(microsecond=0)
AT = (NOW - timedelta(minutes=2)).isoformat()
KO = (NOW + timedelta(hours=2)).isoformat()

def coverage(*args, **kwargs):
    return {"qc_rejected_packets": 0, "pending_qc_packets": 0,
        "calendar_complete": True,
        "fixtures": ({9001: {"fixture": {"date": KO, "status": {"short": "NS"}}}}
                     if args[1] == 39 else {})}

def model_inputs(*args, **kwargs):
    return {"adapter_hash": "TEST_ADAPTER", "source_ids": ["TEST_PACKET"],
        "main": {"sports": {"as_of": AT, "match": {
            "home": "Team A", "away": "Team B", "kickoff": KO}}}}

def prepared(*args, **kwargs):
    return {"model_version": "ORIGINAL", "model_hash": "MODEL_HASH",
        "model": {"team_games": [8, 9], "rates": {"home": 1.5, "away": 1.0}},
        "issues": [{"code": "MISSING_LINEUP"}],
        "candidates": [{"key": "TOTAL:OVER:2.5", "raw": [.50, 0.0, .50],
                        "calibration": "NOT_CALIBRATED"}]}

class ShadowModelTests(unittest.TestCase):
    def test_uses_existing_engine_and_preserves_pass(self):
        with patch.object(shadow, "source_only") as source_only, \
             patch.object(shadow, "league_view", side_effect=coverage) as views, \
             patch.object(shadow, "model_inputs", side_effect=model_inputs) as inputs, \
             patch.object(shadow, "prepare", side_effect=prepared) as engine:
            result = shadow.preview(object(), as_of=AT, ids=[9001])
        source_only.assert_called_once()
        self.assertEqual(views.call_count, 4)
        inputs.assert_called_once()
        engine.assert_called_once()
        self.assertIsNone(engine.call_args.kwargs["calibrator"])
        self.assertIsNone(engine.call_args.kwargs["goal_model"])
        self.assertIsNone(result.get("ev"))
        self.assertFalse(result["monetary_permission"])
        self.assertEqual(result["canonical_predictions_written"], 0)
        self.assertEqual(result["previews"][0]["status"], "UNVALIDATED_SHADOW")
        self.assertEqual(result["previews"][0]["decision"], "PASS")
        self.assertIsNone(result["previews"][0]["ev"])
        self.assertEqual(result["previews"][0]["markets"][0]["raw_win"], .50)

    def test_strictly_disallows_postkickoff_or_unknown_data(self):
        past = (NOW-timedelta(hours=1)).isoformat()
        def past_coverage(*args, **kwargs):
            return {"qc_rejected_packets":0,"pending_qc_packets":0,
                    "calendar_complete":True,
                    "fixtures": {9001:{"fixture":{"date":past,"status":{"short":"NS"}}}}}
        with patch.object(shadow, "source_only"), \
             patch.object(shadow, "league_view", side_effect=past_coverage), \
             patch.object(shadow, "model_inputs") as input_fetch, \
             patch.object(shadow, "prepare") as engine:
            r=shadow.preview(object(), as_of=AT)
        input_fetch.assert_not_called();engine.assert_not_called()
        self.assertEqual(r["inputs_evaluated"],0)

    def test_qc_rejection_blocks_without_engine(self):
        def blocked(*args,**kwargs):
            v=coverage(*args,**kwargs)
            v["qc_rejected_packets"]=1
            return v
        with patch.object(shadow,"source_only"), \
             patch.object(shadow,"league_view",side_effect=blocked), \
             patch.object(shadow,"prepare") as engine:
            r=shadow.preview(object(),as_of=AT)
        engine.assert_not_called()
        self.assertEqual(r["status"],"SHADOW_SOURCE_QC_STOP")
        self.assertFalse(r["monetary_permission"])

    def test_input_shape_bounds(self):
        with patch.object(shadow,"source_only"),patch.object(shadow,"league_view") as view:
            with self.assertRaises(ValueError):
                shadow.preview(object(),as_of=AT,ids=[True])
            with self.assertRaises(ValueError):
                shadow.preview(object(),as_of=AT,ids=[9001,9001])
            view.assert_not_called()

if __name__=="__main__":
    unittest.main()
