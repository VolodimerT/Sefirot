"""Arena shadow invariants; no network, live bets, data mutation or key required."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.arena_shadow import ROLE_SPECS, openai_reviewer, run_arena, main
from sefirot.contracts import Policy, digest
from sefirot.markets import DEFAULT_POOL

UTC = timezone.utc
BASE = datetime(2026, 10, 8, 8, tzinfo=UTC)
iso = lambda minutes: (BASE + timedelta(minutes=minutes)).isoformat()


def sample():
    policy = Policy()
    markets = copy.deepcopy(DEFAULT_POOL[:2])
    candidates = []
    from sefirot.markets import market_of
    for market in markets:
        candidates.append({"market": market, "key": market_of(market).key,
                           "base": [.52, .1, .38], "raw": [.52, .1, .38],
                           "low": [.40, .05, .32], "high": [.64, .15, .48],
                           "calibration": "UNCALIBRATED", "selection_issues": [],
                           "stress_probabilities": [[.42, .1, .48], [.62, .1, .28]]})
    sports = {"as_of": iso(0), "match": {"id": "arena-test-1", "home": "A", "away": "B",
                         "kickoff": iso(180), "format": "REGULATION_90", "sport": "football"},
              "evidence": [{"id": "fact-tactics", "key": "tactics", "value": "unknown"}],
              "history": [], "synthetic": True}
    pred = {"sports": sports, "policy": asdict(policy), "policy_hash": policy.fingerprint,
            "market_pool": markets, "candidates": candidates,
            "sealed_at": iso(1), "captured_prematch": True, "reconstructed": False,
            "model": {"team_games": [10, 12], "effective_games": [8, 10], "tail_bound": 0},
            "scenario": {"selection_constraints": {"avoid_result": False}}, "synthetic": True}
    pred["id"] = digest(pred)
    quotes = [{"market": copy.deepcopy(m), "bookmaker": "SYNTHETIC", "odds": 2.1,
               "observed_at": iso(2), "received_at": iso(3),
               "phase": "ENTRY", "rules": "REGULATION_90"} for m in markets]
    return pred, quotes, iso(3)


class ArenaTests(unittest.TestCase):
    def test_eight_independent_roles_stay_research_only_and_deterministic(self):
        pred, quotes, at = sample()
        before = copy.deepcopy((pred, quotes))
        report = run_arena(pred, quotes, at)
        self.assertEqual(len(report["agents"]), 8)
        self.assertEqual([a["role"] for a in report["agents"]], [r[0] for r in ROLE_SPECS])
        self.assertEqual([a["phase"] for a in report["agents"][:5]], ["sports"]*5)
        self.assertEqual([a["phase"] for a in report["agents"][5:]], ["priced"]*3)
        self.assertEqual(report, run_arena(pred, quotes, at))
        self.assertEqual((pred, quotes), before)
        self.assertEqual(report["verdict"], "ПРОПУСК")
        self.assertEqual(report["stake"], 0)
        self.assertFalse(report["execution_enabled"] or report["betting_allowed"] or report["monetary_permission"])

    def test_ev_math_distinguishes_win_push_loss_and_implied(self):
        pred, quotes, at = sample()
        row = run_arena(pred, quotes, at)["candidate_rows"][0]
        self.assertAlmostEqual(row["ev"], .52*1.1-.38)
        self.assertAlmostEqual(row["implied_probability"], 1/2.1)
        self.assertAlmostEqual(row["fair_odds"], .9/.52)
        self.assertAlmostEqual(row["model_conditional_win"], .52/.9)
        self.assertLess(row["low_ev"], 0)
        self.assertIn("UNCALIBRATED_PROBABILITY", row["blockers"])
        self.assertEqual(run_arena(pred, [], at)["top_ev_market_diagnostic_only"], None)

    def test_hash_tamper_reconstructed_or_postkickoff_refused(self):
        pred, quotes, at = sample()
        for field, replacement in [("reconstructed", True), ("captured_prematch", False)]:
            modified = copy.deepcopy(pred); modified[field] = replacement
            modified.pop("id"); modified["id"] = digest(modified)
            with self.assertRaisesRegex(ValueError, "prematch capture"):
                run_arena(modified, quotes, at)
        pred["candidates"][0]["base"] = [.8, .1, .1]
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            run_arena(pred, quotes, at)
        pred, quotes, at = sample()
        with self.assertRaisesRegex(ValueError, "before kickoff"):
            run_arena(pred, quotes, iso(180))

    def test_prices_must_be_post_seal_and_not_close_or_unsealed(self):
        pred, quotes, at = sample()
        for change in ({"received_at": iso(0)}, {"observed_at": iso(4)},
                       {"phase": "CLOSE"}, {"rules": "EXTRA_TIME"}):
            amended = copy.deepcopy(quotes); amended[0].update(change)
            with self.assertRaises(ValueError):run_arena(pred, amended, at)
        amended = copy.deepcopy(quotes)
        amended[0]["market"] = {"kind": "BTTS", "side": "YES"}
        with self.assertRaisesRegex(ValueError, "expand frozen pool"):
            run_arena(pred, amended, at)

    def test_agent_cannot_invent_sports_evidence_or_see_price_prematurely(self):
        pred, quotes, at = sample()
        calls=[]
        def spy(role, view):
            calls.append((role[0], view))
            return {"status": "UNKNOWN", "explanation": "no data", "evidence_ids": []}
        run_arena(pred, quotes, at, reviewer=spy)
        self.assertEqual(len(calls), 8)
        for _, view in calls[:5]:
            self.assertNotIn("market_rows", view)
            self.assertNotIn("sealed_markets", view)
            self.assertNotIn("odds", json.dumps(view))
        self.assertIn("market_rows", calls[5][1])
        def liar(role, view):
            return {"status": "OK", "explanation": "verified", "evidence_ids": ["nonexistent-source"]}
        with self.assertRaisesRegex(ValueError, "invented"):
            run_arena(pred, quotes, at, reviewer=liar)
        def price_leak(role, view):
            return {"status": "OK", "explanation": "text", "evidence_ids": [pred["candidates"][0]["key"]]}
        with self.assertRaisesRegex(ValueError, "non-visible"):
            run_arena(pred, quotes, at, reviewer=price_leak)

    def test_veto_and_avoid_result_do_not_promote_value(self):
        pred, quotes, at = sample()
        def blocker(role, view):
            return {"status": "BLOCK" if role[0] == "death_test" else "OK", "explanation": "test", "evidence_ids": []}
        report = run_arena(pred, quotes, at, reviewer=blocker)
        self.assertEqual(report["class"], "RED")
        self.assertIsNone(report["research_focus"])
        pred, quotes, at = sample()
        pred["scenario"]["selection_constraints"]["avoid_result"] = True
        pred.pop("id"); pred["id"] = digest(pred)
        report = run_arena(pred, quotes, at)
        self.assertTrue(all("SCENARIO_MARKET_CONFLICT" in r["blockers"] for r in report["candidate_rows"]))

    def test_missing_quotes_and_bad_probability_fails_closed(self):
        pred, quotes, at = sample()
        report = run_arena(pred, [], at)
        self.assertTrue(all("NO_CURRENT_PRICE" in r["blockers"] for r in report["candidate_rows"]))
        pred["candidates"][0]["base"] = [.4, .5, .4]
        pred.pop("id"); pred["id"] = digest(pred)
        with self.assertRaisesRegex(ValueError, "sum to one"):
            run_arena(pred, quotes, at)

    def test_openai_responses_mock_eight_separate_role_calls_and_zero_keys_in_output(self):
        pred, quotes, at = sample()
        requests=[]
        class FakeResponse:
            def __enter__(self):return self
            def __exit__(self, *args):pass
            def read(self, *args):
                return json.dumps({"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps({"status": "UNKNOWN", "explanation": "missing", "evidence_ids": []})}]}]}).encode()
        def fake_open(req, timeout):
            requests.append(json.loads(req.data))
            self.assertEqual(req.get_header("Authorization"), "Bearer test-token-not-real")
            return FakeResponse()
        with patch("scripts.arena_shadow.urlopen", side_effect=fake_open):
            reviewer = openai_reviewer("gpt-test", api_key="test-token-not-real")
            report = run_arena(pred, quotes, at, reviewer=reviewer)
        self.assertEqual(len(requests), 8)
        self.assertEqual([r["model"] for r in requests], ["gpt-test"]*8)
        self.assertTrue(all(r["store"] is False for r in requests))
        self.assertTrue(all("market_rows" not in r["input"] for r in requests[:5]))
        self.assertTrue(all("market_rows" in r["input"] for r in requests[5:]))
        self.assertNotIn("test-token-not-real", json.dumps(report))
        self.assertEqual(report["stake"], 0)

    def test_missing_api_key_does_not_trigger_network(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                openai_reviewer("gpt-5-mini")


if __name__ == "__main__":unittest.main()