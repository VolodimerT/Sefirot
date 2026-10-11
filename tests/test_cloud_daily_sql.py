"""No cloud credentials or network needed; tests never contain actual tickets."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cloud_daily_sql import insert_sql, latest_sql
from daily_autosave import check_report


def synthetic():
    return {"schema": "sefirot-daily-report-v1", "day": "2030-02-01",
            "timezone": "Europe/Kyiv", "origin": "CHAT_DAILY",
            "status": "REPORTED_UNVERIFIED", "source_refs": ["SYNTHETIC_TEST"],
            "report": "SYNTHETIC_TEST_ONLY: no actual wagers."}


class CloudDailySQLTests(unittest.TestCase):
    def test_hex_prevents_sql_injection_and_preserves_utf8(self):
        bad_text = "'); DROP TABLE sefirot.predictions; -- 🐙 Привіт $json$\n"
        data = synthetic()
        data["report"] = bad_text
        sql = insert_sql(data)
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("$json$", sql)
        self.assertIn("decode('", sql)
        hex_part = sql.split("decode('", 1)[1].split("'", 1)[0]
        self.assertEqual(json.loads(bytes.fromhex(hex_part).decode("utf-8")), data)

    def test_noncanonical_input_rejected(self):
        data = synthetic()
        data["status"] = "CORE_BET"
        with self.assertRaises(ValueError):
            insert_sql(data)

    def test_ticket_audit_wrong_day_rejected(self):
        data = synthetic()
        data["origin"] = "TICKET_AUDIT"
        data["report"] = {"schema": "ticket-audit-v1", "status": "REPORTED_UNVERIFIED",
                          "monetary_permission": False, "days": [{"day": "2030-02-02"}]}
        with self.assertRaises(ValueError):
            insert_sql(data)

    def test_no_network_or_credentials(self):
        sql = insert_sql(synthetic())
        self.assertIn("sefirot.save_daily_report", sql)
        self.assertNotIn("https:", sql)
        self.assertNotIn("service_role", sql)

    def test_listing_uses_strict_day(self):
        self.assertIn("LIMIT 10", latest_sql())
        self.assertIn("2030-02-01", latest_sql("2030-02-01"))
        for value in ("2030-02-01';DELETE", "2030-02-30", "../file"):
            with self.assertRaises(ValueError):
                latest_sql(value)


if __name__ == "__main__":
    unittest.main()
