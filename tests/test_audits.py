import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import (AuditLedger, SourceSignal, SystemDecision, DecisionStatus, WaitCase,
                          Execution, PrematchCandidate, screen_candidate,
                          ScoreMarket, Settlement, Branch, settle_score, inspect_market_link)

BASE = datetime(2026, 9, 25, 19, tzinfo=timezone.utc)


def execution(bet_id, event_id, stake="100", payout="0", *, live=False, bet_type="SINGLE", decision_id=None):
    kickoff = BASE+timedelta(hours=1)
    return Execution(bet_id, event_id, kickoff,
                     kickoff+timedelta(minutes=5) if live else BASE,
                     "illustrative", Decimal("1.80"), Decimal(stake), Decimal(payout),
                     bet_type, decision_id)


class HistoricalAuditTests(unittest.TestCase):
    def test_candidate_lock_separates_wait_missing_p_duplicate_and_live(self):
        kickoff = BASE+timedelta(hours=1)
        good = PrematchCandidate("match", kickoff, BASE, "1X2", True, True)
        self.assertEqual(screen_candidate(good, AuditLedger()).status, DecisionStatus.SHADOW_EXPERIMENT)
        self.assertFalse(screen_candidate(good, AuditLedger()).monetary_authorized)
        missing = PrematchCandidate("match", kickoff, BASE, "1X2", False, True)
        self.assertEqual(screen_candidate(missing, AuditLedger()).status, DecisionStatus.NOT_EVALUABLE)
        waiting = PrematchCandidate("match", kickoff, BASE, "1X2", True, False,
                                    "price-feed", BASE+timedelta(minutes=20))
        self.assertEqual(screen_candidate(waiting, AuditLedger()).status, DecisionStatus.WAIT_ACTIVE)
        expired = PrematchCandidate("match", kickoff, BASE+timedelta(minutes=21), "1X2", True, False,
                                    "price-feed", BASE+timedelta(minutes=20))
        self.assertEqual(screen_candidate(expired, AuditLedger()).status, DecisionStatus.WAIT_EXPIRED)
        ledger, _ = AuditLedger().with_execution(execution("already", "match"))
        self.assertEqual(screen_candidate(good, ledger).status, DecisionStatus.PASS_RISK)
        live = PrematchCandidate("new", kickoff, kickoff, "1X2", True, True)
        self.assertIn("LIVE_OUTSIDE_PREMATCH", screen_candidate(live, ledger).reasons)
        compound = PrematchCandidate("new", kickoff, BASE, "BTTS_OVER_2_5", True, True)
        self.assertEqual(screen_candidate(compound, AuditLedger()).status, DecisionStatus.NOT_EVALUABLE)
        express = PrematchCandidate("new", kickoff, BASE, "EXPRESS", True, True)
        self.assertEqual(screen_candidate(express, AuditLedger()).status, DecisionStatus.PASS_RISK)

    def test_synthetic_coupon_accounting_with_sources_separate_from_authority(self):
        # Invented records; accounting fixtures cannot train the forecasting model.
        rows = [
            ("c1", "fixture-1", "10", "16", False, "SINGLE"),
            ("c2", "fixture-2", "10", "0", False, "SINGLE"),
            ("c3", "fixture-3", "10", "0", False, "EXPRESS"),
            ("c4", "fixture-1", "10", "0", True, "SINGLE"),
        ]
        ledger = AuditLedger()
        flags = {}
        for bet, event, stake, payout, live, kind in rows:
            ledger, assessment = ledger.with_execution(execution(bet, event, stake, payout, live=live, bet_type=kind))
            flags[bet] = assessment.flags
            self.assertFalse(assessment.system_bet)
        self.assertEqual(ledger.settled_totals(), (Decimal("40"), Decimal("16"), Decimal("-24")))
        self.assertIn("EXPRESS_NOT_IMPLEMENTED", flags["c3"])
        self.assertIn("DUPLICATE_EVENT_EXPOSURE", flags["c4"])
        self.assertIn("LIVE_OUTSIDE_PREMATCH", flags["c4"])
        self.assertIn("NO_MATCHING_PREMATCH_SYSTEM_DECISION", flags["c1"])

    def test_separate_source_system_and_execution_records(self):
        signal = SourceSignal("src", "match", "analyst", "O3", BASE-timedelta(minutes=2), BASE-timedelta(minutes=1), Decimal("1.90"))
        decision = SystemDecision("review", "match", BASE+timedelta(hours=1), BASE,
                                  DecisionStatus.SHADOW_EXPERIMENT, "research only", source_signal_id="src")
        ledger = AuditLedger().with_signal(signal).with_decision(decision)
        self.assertEqual(len(ledger.signals), 1)
        self.assertEqual(len(ledger.decisions), 1)
        ledger, assessment = ledger.with_execution(execution("coupon", "match", decision_id="review"))
        self.assertIn("NO_MONETARY_AUTHORITY_IN_SHADOW_MODE", assessment.flags)
        self.assertEqual(len(ledger.executions), 1)

    def test_wait_is_explicit_and_has_deadline_before_kickoff(self):
        decision = SystemDecision("wait", "match", BASE+timedelta(hours=1), BASE,
                                  DecisionStatus.WAIT_ACTIVE, "lineup pending")
        with self.assertRaises(ValueError):
            AuditLedger().with_decision(decision)
        case = WaitCase("wait", "witness", "confirmed lineups", BASE+timedelta(minutes=20))
        ledger = AuditLedger().with_decision(decision, case)
        self.assertEqual(ledger.expire_waits(BASE+timedelta(minutes=19)), ())
        self.assertEqual(ledger.expire_waits(BASE+timedelta(minutes=21)), ("wait",))

    def test_late_signal_cannot_be_cited_as_existing_knowledge(self):
        signal = SourceSignal("late", "match", "analyst", "O3", BASE, BASE+timedelta(minutes=1), Decimal("1.90"))
        decision = SystemDecision("review", "match", BASE+timedelta(hours=1), BASE,
                                  DecisionStatus.NOT_EVALUABLE, "no usable source", source_signal_id="late")
        with self.assertRaises(ValueError):
            AuditLedger().with_signal(signal).with_decision(decision)

    def test_duplicate_bet_id_is_rejected_without_overwriting_ledger(self):
        first = execution("coupon", "match")
        ledger, _ = AuditLedger().with_execution(first)
        with self.assertRaises(ValueError):
            ledger.with_execution(first)
        self.assertEqual(len(ledger.executions), 1)

    def test_synthetic_death_branches(self):
        # Two-sided thesis can be true while an extra combined condition fails.
        self.assertEqual(settle_score(ScoreMarket.BTTS_OVER_2_5, 5, 0), Settlement.LOSS)
        self.assertEqual(settle_score(ScoreMarket.BTTS_OVER_2_5, 5, 1), Settlement.WIN)
        self.assertEqual(settle_score(ScoreMarket.BTTS_OVER_2_5, 1, 1), Settlement.LOSS)
        self.assertEqual(settle_score(ScoreMarket.OVER_3, 3, 0), Settlement.PUSH)
        self.assertEqual(settle_score(ScoreMarket.OVER_3, 0, 4), Settlement.WIN)
        self.assertEqual(settle_score(ScoreMarket.OVER_3, 0, 2), Settlement.LOSS)
        self.assertEqual(settle_score(ScoreMarket.AWAY_MINUS_1, 1, 1), Settlement.LOSS)
        self.assertEqual(settle_score(ScoreMarket.AWAY_MINUS_1, 0, 1), Settlement.PUSH)

    def test_market_link_is_only_research_and_can_find_consistent_loss(self):
        branches = (Branch(5, 0, True, "one-way pressure still fits scenario"),
                    Branch(5, 1, True, "opponent scored"))
        result = inspect_market_link(ScoreMarket.BTTS_OVER_2_5, branches)
        self.assertEqual(result.thesis_consistent_losses, (branches[0],))
        self.assertFalse(result.quantified)
        self.assertEqual(result.authority, "RESEARCH_ONLY")
        with self.assertRaises(ValueError):
            inspect_market_link(ScoreMarket.BTTS_OVER_2_5, (Branch(5, 0, True, ""),))


if __name__ == "__main__":
    unittest.main()
