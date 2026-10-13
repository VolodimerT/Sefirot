"""Situation routing + minimum-2.00 alternative research, synthetic-only."""
from datetime import datetime, timedelta, timezone
import unittest

from research.situational_v1 import route_fixture, screen_alternatives

ZERO = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)
stamp = lambda value: value.isoformat()


def fixture(status="NS", kickoff=None, observed=None):
    return {
        "fixture_id": "api-football:fixture:98765", "source_id": "api-football",
        "kickoff": stamp(kickoff or ZERO + timedelta(hours=2)),
        "status": status,
        "status_received_at": stamp(observed or ZERO - timedelta(seconds=15))
    }


def route(now=ZERO, **overrides):
    obj=fixture()
    obj.update(overrides)
    return route_fixture(obj,at=stamp(now))


def candidate(key, odds, *, selection_status="NO_EXPLICIT_CONFLICT",
              price_status="PRICED", observed=ZERO-timedelta(seconds=30),
              calibration_ev_low=0.02, line_id="one"):
    return {"key":key,"selection_status":selection_status,"verdict":"RESEARCH_ONLY",
            "price_status":price_status,"calibration":"UNFITTED",
            "prices":[{"bookmaker":"test-book","odds":odds,
                       "observed_at":stamp(observed),"line_id":line_id,
                       "calibration_ev_low":calibration_ev_low}]}


def comp(*rows):
    return {"schema":"main-market-comparison-v1","at":stamp(ZERO),
            "prediction_id":"test-synthetic-seal","candidates":list(rows),
            "monetary_permission":False,"execution_enabled":False}


class RouteTests(unittest.TestCase):
    def test_kickoff_exact_boundary_and_one_second_either_side(self):
        obj=fixture(kickoff=ZERO,observed=ZERO-timedelta(seconds=2))
        for delta, mode in ((-1,"PREMATCH"),(0,"HOLD"),(1,"HOLD")):
            with self.subTest(delta=delta):
                self.assertEqual(route_fixture(obj,at=stamp(ZERO+timedelta(seconds=delta)))["mode"],mode)

    def test_delayed_status_cannot_refresh_observation_time(self):
        obj=fixture(status="1H",kickoff=ZERO-timedelta(minutes=20),observed=ZERO)
        obj["status_observed_at"]=stamp(ZERO-timedelta(seconds=31))
        self.assertEqual(route_fixture(obj,at=stamp(ZERO))["reason"],"STALE_LIVE_STATUS")

    def test_normal_prematch_is_deep(self):
        r=route()
        self.assertEqual((r["mode"],r["depth"]),("PREMATCH","DEEP"))
        self.assertTrue(r["prematch_candidate"])
        self.assertFalse(r["prematch_core_allowed"])
        self.assertEqual(r["source_attestation"], "NOT_ATTESTED")
        self.assertFalse(r["monetary_permission"])
        self.assertFalse(r["latency_target_validated"])

    def test_near_kickoff_becomes_fast_even_if_deep_requested(self):
        obj=fixture(kickoff=ZERO+timedelta(minutes=10),observed=ZERO-timedelta(seconds=30))
        r=route_fixture(obj,at=stamp(ZERO),detail="DEEP")
        self.assertEqual((r["mode"],r["depth"]),("PREMATCH","FAST"))

    def test_manual_fast_without_simplifying_policy(self):
        r=route_fixture(fixture(),at=stamp(ZERO),detail="FAST")
        self.assertEqual(r["latency_target_ms"],2000)
        self.assertFalse(r["monetary_permission"])

    def test_live_after_kickoff_research_only(self):
        start=ZERO-timedelta(minutes=25)
        current=ZERO
        obj=fixture(status="1H",kickoff=start,observed=current-timedelta(seconds=12))
        r=route_fixture(obj,at=stamp(current),intent="AUTO")
        self.assertEqual(r["mode"],"LIVE_RESEARCH")
        self.assertFalse(r["prematch_core_allowed"])
        self.assertFalse(r["live_betting_allowed"])

    def test_prematch_never_reused_after_start(self):
        o=fixture(kickoff=ZERO-timedelta(seconds=5),observed=ZERO-timedelta(seconds=10))
        r=route_fixture(o,at=stamp(ZERO))
        self.assertEqual(r["mode"],"HOLD")
        self.assertEqual(r["reason"],"KICKOFF_REACHED_NO_INPLAY_CONFIRMATION")

    def test_stale_live_blocks(self):
        o=fixture(status="HT",kickoff=ZERO-timedelta(minutes=50),
                  observed=ZERO-timedelta(minutes=2))
        self.assertEqual(route_fixture(o,at=stamp(ZERO))["reason"],"STALE_LIVE_STATUS")

    def test_live_status_before_kickoff_block(self):
        o=fixture(status="1H",kickoff=ZERO+timedelta(minutes=4),
                  observed=ZERO-timedelta(seconds=1))
        self.assertEqual(route_fixture(o,at=stamp(ZERO))["reason"],"INPLAY_STATUS_CHRONOLOGY_CONFLICT")

    def test_requested_prematch_disallows_live(self):
        o=fixture(status="2H",kickoff=ZERO-timedelta(minutes=55),observed=ZERO)
        self.assertEqual(route_fixture(o,at=stamp(ZERO),intent="PREMATCH")["mode"],"HOLD")

    def test_requested_live_disallows_prematch(self):
        self.assertEqual(route_fixture(fixture(),at=stamp(ZERO),intent="LIVE")["mode"],"HOLD")

    def test_finished_for_recap_not_for_betting(self):
        o=fixture(status="FT",kickoff=ZERO-timedelta(hours=2),observed=ZERO)
        r=route_fixture(o,at=stamp(ZERO))
        self.assertEqual(r["mode"],"POSTMATCH_RECAP")
        self.assertFalse(r["prematch_core_allowed"])

    def test_stopped_is_hold(self):
        for s in ("PST","CANC","SUSP","unexpected"):
            with self.subTest(s=s):
                self.assertEqual(route_fixture(fixture(status=s),at=stamp(ZERO))["mode"],"HOLD")

    def test_near_kickoff_stale(self):
        o=fixture(kickoff=ZERO+timedelta(minutes=7),observed=ZERO-timedelta(seconds=121))
        self.assertEqual(route_fixture(o,at=stamp(ZERO))["reason"],"STALE_PREMATCH_STATUS")

    def test_future_status_receipt(self):
        o=fixture(observed=ZERO+timedelta(seconds=1))
        self.assertEqual(route_fixture(o,at=stamp(ZERO))["reason"],"FUTURE_STATUS_RECEIPT")

    def test_wrong_clock_or_contract_blocks(self):
        o=fixture()
        with self.assertRaises(ValueError):
            route_fixture({**o,"extra":1},at=stamp(ZERO))
        with self.assertRaises(ValueError):
            route_fixture(o,at="2026-10-11 10:00:00")
        with self.assertRaises(ValueError):
            route_fixture(o,at=stamp(ZERO),intent="MIXED")


class AlternativeTests(unittest.TestCase):
    def setUp(self):
        self.r=route()

    def test_duplicate_market_rows_rejected_without_sorting_dicts(self):
        x=candidate("BTTS:YES",2.01)
        out=screen_alternatives(comp(x,x),self.r)
        self.assertEqual(out["reason"],"DUPLICATE_OR_INVALID_MARKET_KEYS")
        self.assertEqual(out["alternatives"],[])

    def test_forged_comparison_is_never_called_verified(self):
        out=screen_alternatives(comp(candidate("BTTS:YES",2.0)),self.r)
        self.assertEqual(out["status"],"CANDIDATES_NOT_ATTESTED")
        self.assertEqual(out["source_provenance"],"INPUT_COMPARISON_NOT_INDEPENDENTLY_ATTESTED")
        for line in (True,{},["line"]):
            self.assertFalse(screen_alternatives(comp(candidate("BTTS:YES",2.01,line_id=line)),self.r)["alternatives"])

    def test_strict_floor_2_inclusive(self):
        c=comp(candidate("1X2:HOME",2.0),candidate("TOTAL:OVER:2.5",1.99))
        out=screen_alternatives(c,self.r)
        self.assertEqual([x["market"] for x in out["alternatives"]],["1X2:HOME"])
        self.assertEqual(out["alternatives"][0]["odds"],2.0)
        self.assertFalse(out["monetary_permission"])

    def test_only_one_per_family(self):
        out=screen_alternatives(comp(
            candidate("1X2:HOME",2.8,calibration_ev_low=0.03),
            candidate("1X2:AWAY",2.9,calibration_ev_low=0.02),
            candidate("BTTS:YES",2.2,calibration_ev_low=0.01),
            candidate("TOTAL:OVER:2.5",2.1,calibration_ev_low=0.0)),self.r)
        self.assertEqual(len(out["alternatives"]),3)
        self.assertEqual(len({x["family"] for x in out["alternatives"]}),3)
        self.assertEqual(out["alternatives"][0]["market"],"1X2:HOME")
        self.assertEqual(out["class"],"RESEARCH_ONLY")

    def test_live_never_receives_prematch_alternatives(self):
        o=fixture(status="1H",kickoff=ZERO-timedelta(minutes=12),observed=ZERO)
        live=route_fixture(o,at=stamp(ZERO))
        out=screen_alternatives(comp(candidate("1X2:HOME",2.8)),live)
        self.assertEqual(out["alternatives"],[])
        self.assertEqual(out["reason"],"PREMATCH_COMPARISON_FORBIDDEN_OUTSIDE_PREMATCH")

    def test_no_quotes_no_fabricated_odds(self):
        out=screen_alternatives(comp(),self.r)
        self.assertEqual(out["status"],"NO_CANDIDATE_GE_2_NOT_ATTESTED")
        self.assertEqual(out["alternatives"],[])

    def test_invalid_price_and_line(self):
        for price in (float("nan"),float("inf"),True,-1,1.999):
            with self.subTest(price=price):
                out=screen_alternatives(comp(candidate("1X2:HOME",price)),self.r)
                self.assertEqual(out["alternatives"],[])
        out=screen_alternatives(comp(candidate("1X2:HOME",2.2,line_id=None)),self.r)
        self.assertFalse(out["alternatives"])

    def test_stale_or_future_price_disallowed(self):
        for delta in (-121,1):
            with self.subTest(delta=delta):
                c=comp(candidate("BTTS:YES",2.12,observed=ZERO+timedelta(seconds=delta)))
                self.assertFalse(screen_alternatives(c,self.r)["alternatives"])

    def test_conflicting_or_not_priced_disallowed(self):
        x=candidate("TOTAL:OVER:2.5",2.22,selection_status="BLOCKED_BY_SCENARIO")
        y=candidate("BTTS:YES",2.1,price_status="MISSING_OR_STALE")
        self.assertFalse(screen_alternatives(comp(x,y),self.r)["alternatives"])

    def test_duplicate_prices_ambiguous(self):
        x=candidate("TOTAL:OVER:2.5",2.5)
        x["prices"].append({**x["prices"][0],"odds":2.9})
        self.assertFalse(screen_alternatives(comp(x),self.r)["alternatives"])

    def test_no_comparison_or_promotion(self):
        self.assertEqual(screen_alternatives(None,self.r)["reason"],"NO_CANONICAL_PRICE_COMPARISON")
        c=comp(candidate("BTTS:YES",2.1))
        c["monetary_permission"]=True
        self.assertFalse(screen_alternatives(c,self.r)["alternatives"])

    def test_research_only_with_unfitted_calibration(self):
        out=screen_alternatives(comp(candidate("BTTS:YES",2.1)),self.r)
        self.assertEqual(out["alternatives"][0]["calibration_status"],"UNFITTED")
        self.assertFalse(out["alternatives"][0]["monetary_permission"])

    def test_stale_comparison(self):
        c=comp(candidate("BTTS:YES",2.1))
        c["at"]=stamp(ZERO-timedelta(seconds=121))
        self.assertEqual(screen_alternatives(c,self.r)["reason"],"STALE_OR_FUTURE_COMPARISON")

    def test_floor_cannot_be_bypassed(self):
        for x in (1.99,True,float("nan"),10001):
            with self.subTest(x=x),self.assertRaises(ValueError):
                screen_alternatives(comp(candidate("BTTS:YES",2.1)),self.r,min_odds=x)

    def test_invalid_count_and_not_fifty_candidates(self):
        with self.assertRaises(ValueError):
            screen_alternatives(comp(candidate("BTTS:YES",2.1)),self.r,limit=4)
        out=screen_alternatives(comp(*([candidate("BTTS:YES",2.1)]*51)),self.r)
        self.assertEqual(out["reason"],"MISSING_OR_UNBOUNDED_GRID")


if __name__ == "__main__":
    unittest.main()
