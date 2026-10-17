"""V4.2 chronological exposure hardening; synthetic only, no wager execution."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.contracts import Policy
from sefirot.risk import size_risk
from sefirot.service import Service


MATCH = {"id": "fixture-v42", "home": "A", "away": "B", "league": "LEAGUE"}
NOW = "2026-10-12T12:00:00+00:00"


def exposure(placed="2026-10-12T10:00:00+00:00", settled=None, *,
             stake=5.0, match_id="different", include_settlement=True):
    row = {"at": placed, "stake": stake, "groups": ["match:" + match_id]}
    if include_settlement and settled is not None:
        row["settled_at"] = settled
    return row


def risk(rows, at=NOW, *, match=MATCH):
    return size_risk(
        win=.60, push=0., odds=2., bankroll=1000., peak=1000.,
        quality=1., exposures=rows, match=match, model="test-model",
        scenario="baseline", factors=[], at=at, policy=Policy())


class ReceiptChronologyTests(unittest.TestCase):
    def test_no_exposure_caps_at_five(self):
        self.assertEqual(risk([])["stake"], 5.0)

    def test_same_fixture_active_exposure_blocks(self):
        out = risk([exposure(match_id="fixture-v42")])
        self.assertEqual(out["stake"], 0.)
        self.assertIn("EVENT_ALREADY_EXPOSED", out["reasons"])

    def test_settlement_before_placement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "settlement precedes placement"):
            risk([exposure(settled="2026-10-12T09:59:59+00:00")])

    def test_future_settlement_receipt_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "future exposure settlement"):
            risk([exposure(settled="2026-10-12T12:00:01+00:00")])

    def test_future_placement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "future exposure"):
            risk([exposure(placed="2026-10-12T12:00:01+00:00")])

    def test_malformed_settlement_receipt_is_rejected(self):
        row = exposure()
        row["settled_at"] = ""
        with self.assertRaises(ValueError):
            risk([row])

    def test_settlement_same_instant_as_placement_not_reclassified(self):
        out = risk([exposure(settled="2026-10-12T10:00:00+00:00")])
        self.assertEqual(out["stake"], 5.0)

    def test_valid_settlement_keeps_same_day_spend(self):
        out = risk([exposure(settled="2026-10-12T11:00:00+00:00", stake=18.)])
        self.assertEqual(out["stake"], 2.0)

    def test_sealed_utc_day_is_unchanged_kyiv_early_hours(self):
        # 01:30 Kyiv October 12 is 22:30 UTC October 11.
        row = exposure(placed="2026-10-12T01:30:00+03:00",
                       settled="2026-10-12T02:00:00+03:00", stake=20.)
        self.assertEqual(risk([row], at="2026-10-12T04:30:00+03:00")["stake"], 5.0)

    def test_sealed_utc_day_is_unchanged_before_kyiv_midnight(self):
        # Two local dates, same UTC Oct 11 accounting day.
        row = exposure(placed="2026-10-11T23:30:00+03:00",
                       settled="2026-10-11T23:45:00+03:00", stake=18.)
        self.assertEqual(risk([row], at="2026-10-12T00:30:00+03:00")["stake"], 2.0)

    def test_offsets_around_spring_dst_do_not_rewrite_risk_day(self):
        # Both timestamps fall on March 29 UTC, despite Kyiv DST offset switch.
        row = exposure(placed="2026-03-29T02:50:00+02:00",
                       settled="2026-03-29T04:30:00+03:00", stake=18.)
        self.assertEqual(risk([row], at="2026-03-29T05:00:00+03:00")["stake"], 2.0)

    def test_settlement_can_use_equivalent_timezone_offset(self):
        row = exposure(placed="2026-10-12T10:00:00+00:00",
                       settled="2026-10-12T14:00:00+03:00", stake=18.)
        self.assertEqual(risk([row], at="2026-10-12T12:00:00+00:00")["stake"], 2.0)


class ServiceGatesTests(unittest.TestCase):
    def test_execution_before_original_decision_is_rejected_upstream(self):
        class FixtureRepository:
            def get(self, table, item):
                if table == "decisions":
                    return {"prediction_id": "p", "at": "2026-10-12T18:00:00+00:00",
                            "candidates": [{"key": "TOTAL:OVER:2.5", "quote": {"observed_at": NOW}}]}
                if table == "predictions":
                    return {"sports": {"match": {"kickoff": "2026-10-12T20:00:00+00:00"}}}
                raise AssertionError("Unexpected repository read")

        svc = Service(FixtureRepository(), Policy(),
                      clock=lambda: datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc))
        e = {"id": "entry", "market": "TOTAL:OVER:2.5", "odds": 2.0,
             "stake": 5.0, "bookmaker": "book", "origin": "EXTERNAL"}
        with self.assertRaisesRegex(ValueError, "prematch execution window"):
            svc.execution("id", e, "2026-10-12T17:00:00+00:00")

    def test_result_before_kickoff_is_rejected_upstream(self):
        class FixtureRepository:
            def get(self, table, item):
                if table == "matches":
                    return {"kickoff": "2026-10-12T18:00:00+00:00"}
                raise AssertionError("Unexpected repository read")
        svc = Service(FixtureRepository(), Policy(),
                      clock=lambda: datetime(2026, 10, 12, 21, 0, tzinfo=timezone.utc))
        result = {"match_id": "fixture-v42", "status": "FINISHED",
                  "home_goals": 1, "away_goals": 1,
                  "finished_at": "2026-10-12T17:59:59+00:00",
                  "received_at": "2026-10-12T19:00:00+00:00",
                  "source": "synthetic"}
        with self.assertRaisesRegex(ValueError, "result chronology"):
            svc.result(result)


if __name__ == "__main__":
    unittest.main()
