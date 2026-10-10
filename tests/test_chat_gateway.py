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


if __name__ == "__main__":
    unittest.main()
