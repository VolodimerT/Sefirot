import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import CaptureJournal, Fact, ProbabilitySeal, SportsOnlySnapshot, ThreeWayQuote, SourceSignal

T = datetime(2026, 9, 26, 9, tzinfo=timezone.utc)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.now = T
        self.journal = CaptureJournal(self.path, lambda: self.now)
        self.snapshot = SportsOnlySnapshot("fixture", T + timedelta(hours=1), T,
            (Fact("sports.home_team", "H", "source", T-timedelta(minutes=2), T),
             Fact("sports.away_team", "A", "source", T-timedelta(minutes=2), T)))

    def seal(self):
        return ProbabilitySeal.create(self.snapshot, "demo-v1", self.now, (.5, .3, .2))

    def test_capture_reopen_and_assessment_preserve_sealed_probability(self):
        self.journal.capture_snapshot(self.snapshot)
        self.now += timedelta(minutes=1)
        self.journal.capture_seal(self.seal())
        self.now += timedelta(minutes=1)
        quote_event = self.journal.capture_quote(ThreeWayQuote("book", self.now, (2.2, 3.3, 4.4)))
        self.now += timedelta(minutes=1)
        self.journal.capture_assessment(quote_event.hash)
        records = CaptureJournal(self.path).read()
        self.assertEqual([e.kind for e in records], ["snapshot", "seal", "quote", "assessment"])
        self.assertEqual(records[-1].payload["report"]["monetary_verdict"], "PASS")
        self.assertEqual(records[-1].payload["report"]["snapshot_digest"], self.snapshot.digest())
        self.assertNotIn("market", str(records[0].payload))

    def test_prevent_quote_before_seal_and_backdated_quote(self):
        self.journal.capture_snapshot(self.snapshot)
        self.now += timedelta(minutes=1)
        with self.assertRaises(ValueError):
            self.journal.capture_quote(ThreeWayQuote("book", self.now, (2.2, 3.3, 4.4)))
        self.journal.capture_seal(self.seal())
        self.now += timedelta(minutes=1)
        with self.assertRaises(ValueError):
            self.journal.capture_quote(ThreeWayQuote("book", T, (2.2, 3.3, 4.4)))
        self.assertEqual(len(self.journal.read()), 2)

    def test_prevent_backdated_seal_after_late_snapshot(self):
        self.now += timedelta(minutes=2)
        self.journal.capture_snapshot(self.snapshot)
        with self.assertRaises(ValueError):
            self.journal.capture_seal(ProbabilitySeal.create(self.snapshot, "old", T + timedelta(minutes=1), (.5,.3,.2)))
        self.assertEqual(len(self.journal.read()), 1)

    def test_corruption_and_torn_write_fail_closed(self):
        self.journal.capture_snapshot(self.snapshot)
        content = self.path.read_text(encoding="utf-8")
        self.path.write_text(content.replace('"fixture"', '"altered"'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "broken hash chain"):
            self.journal.read()
        self.path.write_text(content + '{"kind":"quote"', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "incomplete record"):
            self.journal.read()
        with self.assertRaises(ValueError):
            self.journal.capture_snapshot(self.snapshot)

    def test_lock_and_missing_quote_are_rejected(self):
        self.path.with_name(self.path.name + ".lock").write_text("other writer")
        with self.assertRaises(FileExistsError):
            self.journal.capture_snapshot(self.snapshot)
        self.path.with_name(self.path.name + ".lock").unlink()
        self.journal.capture_snapshot(self.snapshot)
        with self.assertRaises(ValueError):
            self.journal.capture_assessment("not a quote")

    def test_early_quote_and_assessment_after_kickoff_are_rejected(self):
        self.journal.capture_snapshot(self.snapshot)
        self.now += timedelta(minutes=1)
        self.journal.capture_seal(self.seal())
        self.now += timedelta(minutes=1)
        quote = self.journal.capture_quote(ThreeWayQuote("book", self.now, (2.2, 3.3, 4.4)))
        self.now = self.snapshot.kickoff
        with self.assertRaises(ValueError):
            self.journal.capture_assessment(quote.hash)
        self.assertEqual(len(self.journal.read()), 3)

    def test_signal_and_shadow_decision_have_distinct_lineage(self):
        self.journal.capture_snapshot(self.snapshot)
        self.now += timedelta(minutes=1)
        self.journal.capture_seal(self.seal())
        self.now += timedelta(minutes=1)
        signal = SourceSignal("tip-1", "fixture", "analyst", "1X2_HOME",
                              self.now, self.now, Decimal("2.20"))
        self.journal.capture_source_signal(signal)
        quote = self.journal.capture_quote(ThreeWayQuote("book", self.now, (2.2, 3.3, 4.4)))
        self.now += timedelta(minutes=1)
        assessment = self.journal.capture_assessment(quote.hash)
        decision = self.journal.capture_shadow_decision(assessment.hash, "d-1", "tip-1")
        records = CaptureJournal(self.path).read()
        self.assertEqual(records[-1].hash, decision.hash)
        self.assertFalse(records[-1].payload["monetary_authorized"])
        self.assertEqual(records[-1].payload["source_signal_id"], "tip-1")
        self.assertEqual(records[-1].payload["probability_seal"], self.snapshot.digest())

    def test_signal_before_seal_or_after_start_cannot_enter_journal(self):
        self.journal.capture_snapshot(self.snapshot)
        signal = SourceSignal("tip-1", "fixture", "analyst", "1X2_HOME",
                              T, T, Decimal("2.20"))
        with self.assertRaises(ValueError):
            self.journal.capture_source_signal(signal)
        self.now += timedelta(minutes=1)
        self.journal.capture_seal(self.seal())
        with self.assertRaises(ValueError):
            self.journal.capture_source_signal(signal)
        self.assertEqual(len(self.journal.read()), 2)


if __name__ == "__main__":
    unittest.main()
