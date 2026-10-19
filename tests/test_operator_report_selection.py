"""Owned synthetic revisions: operator selection must preserve original seal identity."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service
from research.prematch_readiness import operator_report
from research.chat_answer_contract import AnswerError, build_answer


class OperatorReportSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "owned.sqlite"
        self.base = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
        self.now = self.base
        self.repo = Repository(str(self.path))
        self.addCleanup(self.repo.close)
        self.service = Service(self.repo, clock=lambda: self.now)
        self.inputs = example(self.base)
        self.first = self.service.capture(self.inputs["sports"], self.inputs["markets"])
        self.first_decision = self.decide(self.first, 2)
        revised = deepcopy(self.inputs["sports"])
        revised["as_of"] = self.at(2)
        self.now = self.base + timedelta(minutes=3)
        self.revision = self.service.capture(revised, self.inputs["markets"],
            parent=self.first["id"], reason="NEW_INFORMATION")
        self.assertNotEqual(self.first["id"], self.revision["id"])
        self.assertTrue(self.repo.verify())

    def at(self, minutes):
        return (self.base + timedelta(minutes=minutes)).isoformat()

    def decide(self, prediction, minutes):
        inputs = deepcopy(self.inputs)
        for quote in inputs["quotes"]:
            quote.update(observed_at=self.at(minutes - 1), received_at=self.at(minutes - 1))
        inputs["recheck"]["checked_at"] = self.at(minutes - 1)
        for fact in inputs["recheck"]["evidence"]:
            fact.update(published_at=self.at(minutes - 2), observed_at=self.at(minutes - 2),
                        received_at=self.at(minutes - 1))
        self.now = self.base + timedelta(minutes=minutes)
        decision = self.service.decide(prediction["id"], inputs["quotes"], inputs["recheck"],
            {"bankroll": 0, "peak": 0}, self.at(minutes))
        self.assertEqual(decision["decision"], "PASS")
        self.assertEqual(decision["risk"]["stake"], 0)
        return decision

    def report(self, prediction_id=None, *, minutes=10):
        before = self.path.read_bytes()
        with patch("socket.socket", side_effect=AssertionError("NETWORK_FORBIDDEN")):
            result = operator_report(self.path, at=self.at(minutes),
                prediction_id=prediction_id, include_market_views=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(result["network_requests"], 0)
        self.assertTrue(result["read_only"])
        return result

    def test_revision_without_decision_does_not_inherit_previous_card(self):
        report = self.report(self.revision["id"])
        self.assertEqual(report["ledger_status"], "VERIFIED_LOCAL_ORIGIN_NOT_ATTESTED")
        self.assertEqual(len(report["readiness"]), 1)
        self.assertEqual(report["original_decisions"], [])
        self.assertEqual(report["verified_market_views"], [])

    def test_selected_seal_keeps_all_its_decisions_and_excludes_other_revision(self):
        second_first = self.decide(self.first, 4)
        revised_decision = self.decide(self.revision, 5)
        for prediction, decisions in ((self.first, [self.first_decision, second_first]),
                                      (self.revision, [revised_decision])):
            with self.subTest(revision=prediction["revision"]):
                report = self.report(prediction["id"])
                expected = {d["id"] for d in decisions}
                self.assertEqual({d["decision_id"] for d in report["original_decisions"]}, expected)
                self.assertEqual({d["forecast_seal_id"] for d in report["original_decisions"]},
                                 {prediction["id"]})
                self.assertEqual({v["decision_id"] for v in report["verified_market_views"]}, expected)
        unfiltered = self.report()
        self.assertEqual(len(unfiltered["readiness"]), 2)
        self.assertEqual({d["decision_id"] for d in unfiltered["original_decisions"]},
                         {self.first_decision["id"], second_first["id"], revised_decision["id"]})
        self.assertEqual(len(unfiltered["verified_market_views"]), 3)

    def test_explicit_empty_selection_cannot_expand_to_whole_ledger(self):
        for selection in ("", False, 0):
            with self.subTest(selection=selection):
                report = self.report(selection)
                self.assertEqual(report["ledger_status"], "UNREADABLE_OR_UNVERIFIABLE")
                for field in ("readiness", "original_decisions", "verified_market_views"):
                    self.assertEqual(report[field], [])

    def test_revision_not_yet_sealed_at_cutoff_is_unavailable(self):
        report = self.report(self.revision["id"], minutes=2)
        self.assertEqual(report["ledger_status"], "UNREADABLE_OR_UNVERIFIABLE")
        self.assertEqual(report["original_decisions"], [])
        self.assertEqual(report["verified_market_views"], [])

    def legacy_archive(self, fixture_id="SYNTHETIC LEGACY / fixture", *, minutes=6):
        inputs = example(self.base, match_id=fixture_id)
        self.now = self.base + timedelta(minutes=4)
        prediction = self.service.capture(inputs["sports"], inputs["markets"])
        decision = self.decide(prediction, minutes)
        return prediction, decision

    def test_unsupported_fixture_ids_preserve_supported_originals(self):
        legacy = [self.legacy_archive(value)[1] for value in
                  ("SYNTHETIC LEGACY / fixture", "x" * 129)]
        report = self.report()
        self.assertEqual(report["ledger_status"], "VERIFIED_LOCAL_ORIGIN_NOT_ATTESTED")
        self.assertEqual(report["archive_view_status"], "PARTIAL")
        self.assertEqual(len(report["readiness"]), 4)
        self.assertEqual([r["decision_id"] for r in report["original_decisions"]],
                         [self.first_decision["id"]])
        self.assertEqual([r["decision_id"] for r in report["verified_market_views"]],
                         [self.first_decision["id"]])
        self.assertEqual({r["decision_id"] for r in report["unavailable_original_decisions"]},
                         {d["id"] for d in legacy})
        self.assertIn("ARCHIVE_FIXTURE_ID_UNSUPPORTED", report["missing_evidence"])
        self.assertFalse(report["monetary_permission"])

    def test_selected_legacy_archive_is_unavailable_without_changing_chat_contract(self):
        prediction, decision = self.legacy_archive()
        with self.assertRaisesRegex(AnswerError, r"STRING_PATTERN:\$\.fixture_id"):
            build_answer(decision["match_id"], [decision["match_id"]],
                         at=self.now, repo=self.repo, decision_id=decision["id"], archive=True)
        report = self.report(prediction["id"])
        self.assertEqual(report["ledger_status"], "VERIFIED_LOCAL_ORIGIN_NOT_ATTESTED")
        self.assertEqual(report["archive_view_status"], "UNAVAILABLE")
        self.assertEqual(len(report["readiness"]), 1)
        self.assertEqual(report["original_decisions"], [])
        self.assertEqual(report["verified_market_views"], [])
        self.assertEqual(report["unavailable_original_decisions"], [{
            "decision_id": decision["id"], "forecast_seal_id": prediction["id"],
            "status": "UNAVAILABLE", "reason": "ARCHIVE_FIXTURE_ID_UNSUPPORTED"}])
        self.assertGreater(report["audit_events"], 0)

    def test_selecting_supported_seal_excludes_legacy_blockers(self):
        self.legacy_archive()
        report = self.report(self.first["id"])
        self.assertEqual(report["archive_view_status"], "COMPLETE")
        self.assertEqual(report["unavailable_original_decisions"], [])
        self.assertNotIn("ARCHIVE_FIXTURE_ID_UNSUPPORTED", report["missing_evidence"])
        self.assertEqual([r["decision_id"] for r in report["original_decisions"]],
                         [self.first_decision["id"]])

    def test_legacy_decision_after_cutoff_cannot_appear_as_unavailable(self):
        prediction, decision = self.legacy_archive(minutes=12)
        report = self.report(prediction["id"], minutes=10)
        self.assertEqual(report["archive_view_status"], "COMPLETE")
        self.assertEqual(report["unavailable_original_decisions"], [])
        self.assertEqual(report["original_decisions"], [])
        report = self.report(prediction["id"], minutes=12)
        self.assertEqual([r["decision_id"] for r in report["unavailable_original_decisions"]],
                         [decision["id"]])

    def test_corrupt_ledger_is_never_presented_as_unsupported_archive(self):
        self.legacy_archive()
        # Only this owned disposable fixture is corrupted; production triggers
        # correctly prevent the direct UPDATE used by the first test draft.
        trigger = self.repo.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='decisions' AND sql LIKE '%BEFORE UPDATE%'").fetchone()
        self.assertIsNotNone(trigger)
        self.repo.db.execute('DROP TRIGGER "' + trigger[0].replace('"', '""') + '"')
        self.repo.db.execute("UPDATE decisions SET at='2030-01-01T00:00:00+00:00'")
        report = self.report()
        self.assertEqual(report["ledger_status"], "INTEGRITY_FAILED")
        for key in ("readiness", "original_decisions", "verified_market_views",
                    "unavailable_original_decisions"):
            self.assertEqual(report[key], [])

    def test_unexpected_verifier_error_still_closes_entire_report(self):
        self.legacy_archive()
        later = self.decide(self.revision, 7)
        for error in ("PRIVATE_SYNTHETIC_FAILURE", "STRING_PATTERN:$.requested_scope[0]"):
            def checked(*args, **kwargs):
                if kwargs["decision_id"] == later["id"]:
                    raise AnswerError(error)
                return build_answer(*args, **kwargs)
            with self.subTest(error=error), patch(
                    "research.prematch_readiness.build_answer", side_effect=checked):
                report = self.report()
            self.assertEqual(report["ledger_status"], "UNREADABLE_OR_UNVERIFIABLE")
            self.assertEqual(report["archive_view_status"], "UNAVAILABLE")
            for key in ("readiness", "original_decisions", "verified_market_views",
                        "unavailable_original_decisions"):
                self.assertEqual(report[key], [])
            self.assertNotIn(error, str(report))

    def test_selection_respects_decision_cutoff_without_hiding_archive(self):
        self.decide(self.first, 6)
        report = self.report(self.first["id"], minutes=4)
        self.assertEqual([d["decision_id"] for d in report["original_decisions"]],
                         [self.first_decision["id"]])
        self.assertEqual([v["decision_id"] for v in report["verified_market_views"]],
                         [self.first_decision["id"]])
        self.assertTrue(report["verified_market_views"][0]["archive_only"])
        self.assertFalse(report["verified_market_views"][0]["fresh_quote_attested"])


if __name__ == "__main__":
    unittest.main()
