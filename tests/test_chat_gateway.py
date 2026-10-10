"""Smoke tests for the authenticated SEFIROT HTTP bridge."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("chat_gateway", ROOT / "scripts" / "chat_gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class BridgeTests(unittest.TestCase):
    def test_missing_secret_fails_closed(self):
        with patch.dict("os.environ", {"SEFIROT_BRIDGE_TOKEN": "weak"}):
            with self.assertRaises(RuntimeError):
                gateway.configured_token()

    def test_real_core_synthetic_demo(self):
        result = gateway.run_demo()
        self.assertTrue(result["synthetic"])
        self.assertTrue(result["replay_matches"])
        self.assertTrue(result["ledger_integrity"])
        self.assertFalse(result["money_authorized"])
        self.assertFalse(result["persistent_storage"])

    def test_status_of_empty_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict("os.environ", {"SEFIROT_BRIDGE_DB": str(Path(folder) / "ledger.sqlite")}):
                result = gateway.execute("status", {})
                self.assertEqual(result["stored_predictions"], 0)
                self.assertEqual(result["stored_decisions"], 0)
                self.assertTrue(result["ledger_integrity"])
                self.assertFalse(result["money_authorized"])

    def test_past_kickoff_rejected_by_canonical_core(self):
        from datetime import datetime, timedelta, timezone
        from sefirot.fixtures import example
        case = example(datetime.now(timezone.utc) - timedelta(days=1))
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict("os.environ", {"SEFIROT_BRIDGE_DB": str(Path(folder) / "ledger.sqlite")}):
                with self.assertRaisesRegex(ValueError, "prematch"):
                    gateway.execute("capture", {"sports": case["sports"]})

    def test_real_prematch_revision_requires_explicit_parent_and_reason(self):
        from datetime import datetime, timedelta, timezone
        from sefirot.fixtures import example
        from copy import deepcopy
        base = datetime.now(timezone.utc).replace(microsecond=0)
        case = example(base, "bridge-revision-fixture")
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict("os.environ", {"SEFIROT_BRIDGE_DB": str(Path(folder) / "ledger.sqlite")}):
                first = gateway.execute("capture", {"sports": case["sports"], "markets": case["markets"]})
                self.assertEqual(first["stage"], "FORECAST_SEALED")
                newer = deepcopy(case["sports"])
                newer["as_of"] = (base + timedelta(seconds=10)).isoformat()
                newer["history"] = newer["history"][1:]
                with self.assertRaisesRegex(ValueError, "parent and reason"):
                    gateway.execute("capture", {"sports": newer, "markets": case["markets"],
                                                "parent": first["prediction_id"]})
                second = gateway.execute("capture", {"sports": newer, "markets": case["markets"],
                                                  "parent": first["prediction_id"], "reason": "NEW_INFORMATION"})
                self.assertNotEqual(first["prediction_id"], second["prediction_id"])
                self.assertEqual(second["stage"], "FORECAST_SEALED")



if __name__ == "__main__":
    unittest.main()
