"""Daily report archive tests: synthetic samples, never actual wagers."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from daily_autosave import _store_lock, canonical, check_report, main, save, verify


def daily():
    return {"schema": "sefirot-daily-report-v1", "day": "2030-02-01",
            "timezone": "Europe/Kyiv", "origin": "CHAT_DAILY",
            "status": "REPORTED_UNVERIFIED", "source_refs": [],
            "report": "Synthetic daily recap. CORE: SEFIROT_NOT_EXECUTED. PASS."}


class DailyAutosaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name) / "private"

    def test_initial_save_and_verify(self):
        saved = save(daily(), self.store)
        self.assertTrue(saved["new_version"])
        self.assertEqual(saved["versions_for_day"], 1)
        self.assertEqual(verify(self.store)["snapshots"], 1)
        self.assertEqual(json.loads(Path(saved["path"]).read_text()), daily())

    def test_repeat_is_idempotent_and_does_not_mutate_latest(self):
        first = save(daily(), self.store)
        before = (self.store / "latest.json").read_bytes()
        second = save(daily(), self.store)
        self.assertFalse(second["new_version"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(before, (self.store / "latest.json").read_bytes())

    def test_corrected_report_gets_new_version_never_overwrites(self):
        first = save(daily(), self.store)
        changed = daily(); changed["report"] += " Corrected evidence."
        second = save(changed, self.store)
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(second["versions_for_day"], 2)
        self.assertEqual(verify(self.store)["snapshots"], 2)
        self.assertEqual(json.loads(Path(first["path"]).read_text()), daily())

    def test_wrong_schema_and_day_rejected_without_writes(self):
        for field, value in (("schema", "wrong"), ("day", "2030-02-30"),
                             ("timezone", "UTC"), ("status", "CERTIFIED_BET"),
                             ("origin", "UNKNOWN"), ("report", ""), ("source_refs", [12])):
            with self.subTest(field=field):
                changed = daily(); changed[field] = value
                with self.assertRaises(ValueError):
                    save(changed, self.store)
        self.assertFalse(self.store.exists())

    def test_tampered_content_and_pointer_detected(self):
        saved = save(daily(), self.store)
        path = Path(saved["path"])
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            verify(self.store)
        path.write_bytes(canonical(daily()))
        pointer = self.store / "latest.json"
        pointer.write_text('{"day":"2030-02-01"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "POINTER"):
            verify(self.store)

    def test_locked_store_fails_closed(self):
        self.store.mkdir(parents=True)
        with _store_lock(self.store):
            with self.assertRaisesRegex(ValueError, "ARCHIVE_BUSY"):
                save(daily(), self.store)
        self.assertFalse(list(self.store.glob("????-??-??/*.json")))

    def test_nan_and_oversize_rejected(self):
        changed = daily(); changed["report"] = "a" * 512_000
        with self.assertRaisesRegex(ValueError, "TOO_LARGE"):
            save(changed, self.store)
        with self.assertRaises(ValueError):
            canonical({"bad": float("nan")})

    def test_ticket_audit_requires_matching_single_day(self):
        report = daily(); report["origin"] = "TICKET_AUDIT"
        report["report"] = {"schema": "ticket-audit-v1", "status": "REPORTED_UNVERIFIED",
                            "monetary_permission": False, "days": [{"day": "2030-02-01"}]}
        self.assertEqual(save(report, self.store)["versions_for_day"], 1)
        for invalid in ({"day": "2030-02-02"},):
            bad = copy.deepcopy(report); bad["report"]["days"] = [invalid]
            with self.assertRaisesRegex(ValueError, "INVALID_TICKET_AUDIT"):
                check_report(bad)

    def test_cli_save_verify_and_input_validation(self):
        path = Path(self.temp.name) / "report.json"
        path.write_bytes(canonical(daily()))
        self.assertEqual(main(["--report", str(path), "--store", str(self.store)]), 0)
        self.assertEqual(main(["--verify", "--store", str(self.store)]), 0)
        path.write_text("{}")
        self.assertEqual(main(["--report", str(path), "--store", str(self.store)]), 2)

    def test_malformed_ticket_day_lists_fail_closed(self):
        report = daily(); report["origin"] = "TICKET_AUDIT"
        for value in ("bad", None, [None], 5, [{"day": "2030-02-01"}, {}]):
            bad = copy.deepcopy(report)
            bad["report"] = {"schema": "ticket-audit-v1", "status": "REPORTED_UNVERIFIED",
                             "monetary_permission": False, "days": value}
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "INVALID_TICKET_AUDIT"):
                save(bad, self.store)

    def test_retry_older_day_keeps_latest_pointer(self):
        old = save(daily(), self.store)
        newer = daily(); newer["day"] = "2030-02-02"
        saved = save(newer, self.store)
        self.assertFalse(save(daily(), self.store)["new_version"])
        self.assertEqual(verify(self.store)["latest"]["sha256"], saved["sha256"])
        self.assertNotEqual(old["sha256"], saved["sha256"])

    def test_partial_uncommitted_temp_does_not_change_archive(self):
        saved = save(daily(), self.store)
        path = Path(saved["path"]).parent / ".pending-orphan"
        path.write_text("partial")
        self.assertEqual(verify(self.store)["snapshots"], 1)
        self.assertFalse(save(daily(), self.store)["new_version"])

    def test_latest_pointer_missing_detected(self):
        save(daily(), self.store)
        (self.store / "latest.json").unlink()
        with self.assertRaisesRegex(ValueError, "MISSING_LATEST"):
            verify(self.store)

    def test_extra_keys_and_non_dict_reports_rejected(self):
        for data in ([], None, "hello", {**daily(), "money_permission": True}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                save(data, self.store)

    def test_existing_ticket_audit_sample_autosaves_in_one_invocation(self):
        root = Path(__file__).resolve().parents[1]
        example = root / "examples" / "ops_ticket_audit.json"
        self.assertEqual(main(["--ticket-input", str(example), "--store", str(self.store)]), 0)
        result = verify(self.store)
        self.assertEqual(result["snapshots"], 1)
        data = json.loads(next(self.store.glob("????-??-??/*.json")).read_text())
        self.assertEqual(data["origin"], "TICKET_AUDIT")
        self.assertEqual(data["status"], "REPORTED_UNVERIFIED")
        self.assertFalse(data["report"]["monetary_permission"])

    def test_multi_day_ticket_input_fails_without_saving(self):
        root = Path(__file__).resolve().parents[1]
        example = json.loads((root / "examples" / "ops_ticket_audit.json").read_text())
        example["tickets"][-1]["day"] = "2030-01-02"
        inp = Path(self.temp.name) / "two_days.json"
        inp.write_text(json.dumps(example))
        self.assertEqual(main(["--ticket-input", str(inp), "--store", str(self.store)]), 2)
        self.assertFalse(list(self.store.glob("????-??-??/*.json")))

    def test_no_public_repo_mutation(self):
        self.assertNotIn("github", str(self.store))
        self.assertNotIn("monetary_permission", daily())


if __name__ == "__main__":
    unittest.main()
