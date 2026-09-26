import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from run_sefirot import analyze
from sefirot_core import CaptureJournal

T = datetime(2026, 9, 26, 11, tzinfo=timezone.utc)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.history = self.path / "history.json"
        rows = []
        for n in range(1, 8):
            kickoff = T - timedelta(days=15-n)
            rows.append(dict(match_id=f"m{n}", kickoff=kickoff.isoformat(),
                             result_received_at=(kickoff+timedelta(hours=2)).isoformat(),
                             home_team="A" if n%2 else "C", away_team="B" if n%2 else "A",
                             home_goals=n%3, away_goals=(n+1)%2, source="test fixture"))
        self.history.write_text(json.dumps(rows), encoding="utf-8")
        self.journal = self.path / "capture.jsonl"
        self.lines = []

    def run_analysis(self, reader, confirmed=True):
        return analyze(match_id="fixture", kickoff=T+timedelta(hours=2), home="A", away="B",
                       source="test fixture", published_at=T-timedelta(hours=1),
                       history_path=self.history, journal_path=self.journal, confirmed=confirmed,
                       reader=reader, writer=self.lines.append, clock=lambda: T)

    def test_complete_analysis_seals_before_reading_market_and_passes(self):
        answers = iter(("example-book", "1.8 4.0 6.0"))
        def reader(prompt):
            self.assertEqual([e.kind for e in CaptureJournal(self.journal).read()], ["snapshot", "seal"])
            return next(answers)
        self.assertEqual(self.run_analysis(reader), "PASS")
        kinds = [e.kind for e in CaptureJournal(self.journal).read()]
        self.assertEqual(kinds, ["snapshot", "seal", "quote", "assessment", "decision"])
        self.assertTrue(any("EV" in line for line in self.lines))
        self.assertTrue(any("вердикт: PASS" in line for line in self.lines))

    def test_unconfirmed_source_never_prompts_for_odds(self):
        self.assertEqual(self.run_analysis(lambda prompt: self.fail("must not request odds"), False), "PASS")
        self.assertEqual([e.kind for e in CaptureJournal(self.journal).read()], ["snapshot"])

    def test_incomplete_history_never_requests_market(self):
        self.history.write_text("[]", encoding="utf-8")
        self.assertEqual(self.run_analysis(lambda prompt: self.fail("no forecast should prompt")), "PASS")
        self.assertEqual([e.kind for e in CaptureJournal(self.journal).read()], ["snapshot"])

    def test_invalid_odds_leave_sealed_forecast_without_decision(self):
        answers = iter(("example-book", "1.0 4.0 6.0"))
        self.assertEqual(self.run_analysis(lambda _: next(answers)), "PASS")
        self.assertEqual([e.kind for e in CaptureJournal(self.journal).read()], ["snapshot", "seal"])


if __name__ == "__main__":
    unittest.main()
