"""Synthetic provenance/anti-leakage cases; no fit, provider I/O or real data."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from scripts.calibration_quality_audit import audit, audit_originals, cohort_errors
from sefirot.contracts import digest, time
from sefirot.forward import create_plan
from sefirot.forward_scorecard import _receipt
from sefirot.football_provider import select_prematch
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import validate_packet
from test_calibration_quality_audit import scorecard, resign
from test_operations_upgrade import packet, row, stamp, NOW


def plan(role, mid, day, *, registered=-1):
    value={"role":role,"at":stamp(registered*24),
        "calibrator_id":"synthetic-frozen" if role=="HOLDOUT" else None,
        "members":[{"match":{"id":mid,"kickoff":stamp(day*24)}}]}
    value["id"]=digest(value)
    return value


class EvidenceAuditTests(unittest.TestCase):
    def test_boolean_or_fractional_counters_are_not_integer_denominators(self):
        for field in ("planned_fixtures","scored_fixtures","market_observations","forecasts_recomputed"):
            for invalid in (True,False,1.0):
                with self.subTest(field=field,invalid=invalid):
                    s=scorecard(n=1,markets=("1X2:HOME",));s[field]=invalid
                    with self.assertRaisesRegex(ValueError,"integer"):audit(resign(s))

    def test_duplicate_declared_group_is_not_silently_deduplicated(self):
        s=scorecard(n=2);s["groups"].append(deepcopy(s["groups"][0]))
        with self.assertRaisesRegex(ValueError,"duplicate declared"):audit(resign(s))

    def test_http_status_must_be_original_integer_not_float_string_or_bool(self):
        for invalid in (200.0,"200",True):
            p=packet([row(1)]);p["receipt"]["http_status"]=invalid
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):validate_packet(p)
                self.assertFalse(_receipt(p["receipt"],stamp()))
        p=packet([row(1)]);self.assertTrue(_receipt(p["receipt"],stamp()))

    def test_prematch_known_final_score_cannot_enter_target_normalization(self):
        for score in ((2,1),(0,0),(None,1)):
            p=packet([row(100,status="NS",hours=3,score=score)])
            with self.subTest(score=score),self.assertRaisesRegex(ValueError,"contains a result"):
                select_prematch(p,100)
        p=packet([row(100,status="NS",hours=3,score=(None,None))])
        self.assertEqual(select_prematch(p,100)[1]["id"],"api-football:fixture:100")

    def test_malformed_prematch_score_container_is_closed(self):
        for score in ([],{"fulltime":[]},{"fulltime":True}):
            p=packet([row(100,status="NS",hours=3,score=(None,None))])
            p["data"]["response"][0]["score"]=score
            with self.subTest(score=score),self.assertRaises(ValueError):select_prematch(p,100)

    def test_source_receipt_after_forecast_cutoff_or_backwards_request_is_not_evidence(self):
        p=packet([row(1)])
        self.assertFalse(_receipt(p["receipt"],stamp(-1)))
        p["receipt"]["request_started_at"]=stamp(1)
        self.assertFalse(_receipt(p["receipt"],stamp()))

    def test_no_data_means_null_metrics_and_draft_plan_not_a_holdout(self):
        with patch("socket.socket",side_effect=AssertionError("NETWORK_FORBIDDEN")):
            out=audit_originals(at=stamp())
        self.assertEqual(out["status"],"INSUFFICIENT_REAL_DATA")
        self.assertTrue(all(v is None for v in out["metrics"].values()))
        self.assertIsNone(out["planned_fixtures"])
        self.assertEqual(len(out["groups"]),7)
        self.assertIsNone(out["prospective_plan"]["fixture_ids"])
        self.assertFalse(out["holdout_passed"])
        self.assertFalse(out["statistical_profitability_proven"])
        self.assertEqual(out["prospective_plan"]["network_requests"],0)

    def test_missing_or_corrupt_ledger_is_never_created_or_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"absent"/"missing.sqlite"
            self.assertEqual(audit_originals(p,at=stamp())["ledger_status"],"ABSENT")
            self.assertFalse(p.parent.exists())
            p=Path(directory)/"bad.sqlite";p.write_bytes(b"synthetic corrupt bytes");before=p.read_bytes()
            self.assertEqual(audit_originals(p,at=stamp())["ledger_status"],"UNVERIFIABLE")
            self.assertEqual(p.read_bytes(),before)

    def test_original_unscored_cohort_retains_full_denominator_without_metrics_or_source_attestation(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"original.sqlite"
            with closing(Repository(str(p))) as repo:
                service=Service(repo,clock=lambda:NOW)
                original=create_plan(service,packet([row(100,status="NS",hours=3,score=(None,None))]),
                    {9:"LOWER"},role="CALIBRATION",source_reliability=.95)
            before=p.read_bytes()
            out=audit_originals(p,at=stamp(24))
            self.assertEqual(p.read_bytes(),before)
            self.assertEqual(out["status"],"NOT_VERIFIED")
            self.assertEqual(out["source_inventory"][0]["plan_id"],original["id"])
            self.assertEqual(out["source_inventory"][0]["declared_fixtures"],1)
            self.assertEqual(out["source_inventory"][0]["locally_scorable_fixtures"],0)
            self.assertTrue(all(v is None for v in out["metrics"].values()))
            self.assertFalse(out["source_inventory"][0]["real_source_eligible"])

    def test_duplicate_fixture_across_or_inside_cohort_is_quarantined(self):
        self.assertIn("DUPLICATE_OR_CROSS_COHORT_FIXTURE",
            cohort_errors([plan("CALIBRATION","same",1),plan("HOLDOUT","same",2)]))
        p=plan("TRAIN","same",1);p["members"]*=2;p.pop("id");p["id"]=digest(p)
        self.assertIn("DUPLICATE_OR_CROSS_COHORT_FIXTURE",cohort_errors([p]))

    def test_train_calibration_holdout_windows_are_strictly_time_separate(self):
        self.assertEqual(cohort_errors([plan("TRAIN","t",1),plan("CALIBRATION","c",2),plan("HOLDOUT","h",3)]),[])
        self.assertIn("COHORT_TIME_WINDOWS_OVERLAP",
            cohort_errors([plan("CALIBRATION","c",3),plan("HOLDOUT","h",2)]))

    def test_post_kickoff_registration_unfrozen_fit_or_old_test_role_cannot_pass(self):
        self.assertIn("PLAN_NOT_FROZEN_BEFORE_KICKOFF",
            cohort_errors([plan("CALIBRATION","late",1,registered=1)]))
        p=plan("HOLDOUT","h",3);p["calibrator_id"]=None;p.pop("id");p["id"]=digest(p)
        self.assertIn("HOLDOUT_WITHOUT_FROZEN_CALIBRATOR",cohort_errors([p]))
        self.assertIn("UNKNOWN_COHORT_ROLE",cohort_errors([plan("TEST","seen",1)]))

    def test_content_identity_of_cohort_cannot_be_relabelled(self):
        p=plan("CALIBRATION","c",1);p["members"][0]["match"]["id"]="changed"
        self.assertIn("COHORT_CONTENT_ID_MISMATCH",cohort_errors([p]))

    def test_actual_frozen_fit_must_precede_registration_and_not_include_holdout(self):
        for fit_at,ids,expected in ((stamp(24),["c"],"FIT_AFTER_HOLDOUT_REGISTRATION"),
                                    (stamp(-48),["h"],"HOLDOUT_OVERLAPS_FIT_IDS")):
            fit={"fit_at":fit_at,"fit_ids":ids};fit["hash"]=digest(fit)
            p=plan("HOLDOUT","h",3);p["calibrator_id"]=fit["hash"];p.pop("id");p["id"]=digest(p)
            self.assertIn(expected,cohort_errors([p],[fit]))

    def test_missing_or_tampered_fit_cannot_be_silently_declared_frozen(self):
        p=plan("HOLDOUT","h",3)
        self.assertIn("ORIGINAL_FROZEN_FIT_NOT_FOUND",cohort_errors([p],[]))
        fit={"fit_at":stamp(-48),"fit_ids":["c"]};fit["hash"]=digest(fit)
        p["calibrator_id"]=fit["hash"];p.pop("id");p["id"]=digest(p)
        fit["fit_ids"]=["changed"]
        self.assertIn("FROZEN_FIT_CONTENT_MISMATCH",cohort_errors([p],[fit]))

    def test_void_retains_denominator_but_never_becomes_loss(self):
        s=scorecard(n=2);s["fixtures"][1]["status"]="VOID_NOT_SCORED"
        s["observations"]=[r for r in s["observations"] if r["match_id"]==s["fixtures"][0]["match_id"]]
        s.update(scored_fixtures=1,market_observations=2,fixture_coverage=.5)
        out=audit(resign(s))
        self.assertEqual(out["planned_fixtures"],2)
        self.assertEqual(out["scored_fixtures"],1)
        self.assertEqual(out["fixture_status_counts"]["VOID_NOT_SCORED"],1)
        self.assertFalse(out["holdout_passed"])

    def test_push_keeps_three_way_probabilities_and_impossible_push_is_rejected(self):
        s=scorecard(n=1,markets=("TOTAL:OVER:2",))
        s["observations"][0].update(outcome="PUSH",raw=[.4,.2,.4],base=[.4,.2,.4])
        out=audit(resign(s));self.assertEqual(out["market_observations"],1)
        s=scorecard(n=1,markets=("1X2:HOME",));s["observations"][0]["outcome"]="PUSH"
        with self.assertRaisesRegex(ValueError,"impossible PUSH"):audit(resign(s))

    def test_new_synthetic_fixture_is_versioned_old_source_bytes_not_rewritten(self):
        old=json.loads((ROOT/"tests/fixtures/prematch_issue58/source.json").read_text())
        new=json.loads((ROOT/"tests/fixtures/prematch_issue59_source_v2/source.json").read_text())
        self.assertNotEqual(old["hash"],new["hash"])
        self.assertEqual(old["packets"][0]["data"]["response"][0]["score"]["fulltime"],{"home":2,"away":1})
        self.assertEqual(new["packets"][0]["data"]["response"][0]["score"]["fulltime"],{"home":None,"away":None})

    def test_train_holdout_order_is_checked_without_an_intermediate_calibration(self):
        self.assertIn("COHORT_TIME_WINDOWS_OVERLAP",
            cohort_errors([plan("TRAIN","t",4),plan("HOLDOUT","h",2)]))
        self.assertEqual(cohort_errors([plan("TRAIN","t",1),plan("HOLDOUT","h",2)]),[])

    def test_frozen_fit_ids_are_unique_nonempty_string_list_not_iterable_surrogates(self):
        for ids in ("train-fixture",{"train-fixture":True},["t","t"],[],None,[True],[42],[" "]):
            fit={"fit_at":stamp(-48),"fit_ids":ids};fit["hash"]=digest(fit)
            p=plan("HOLDOUT","h",3);p["calibrator_id"]=fit["hash"];p.pop("id");p["id"]=digest(p)
            with self.subTest(ids=ids):
                self.assertIn("MALFORMED_FROZEN_FIT_IDS",cohort_errors([p],[fit]))

    def test_malformed_cohort_shape_is_reported_without_uncaught_parser_errors(self):
        for member in (None,{}, {"match":[]},{"match":{"id":True,"kickoff":stamp(24)}},
                       {"match":{"id":" ","kickoff":stamp(24)}}):
            p=plan("CALIBRATION","c",1);p["members"]=[member];p.pop("id");p["id"]=digest(p)
            with self.subTest(member=member):
                self.assertIn("MALFORMED_COHORT",cohort_errors([p]))
        p=plan("CALIBRATION","c",1);p["at"]=None;p.pop("id");p["id"]=digest(p)
        self.assertIn("MALFORMED_COHORT",cohort_errors([p]))
        self.assertIn("MALFORMED_COHORT_COLLECTION",cohort_errors(None))
        self.assertIn("MALFORMED_FROZEN_FIT_COLLECTION",cohort_errors([],{}))

    def test_malformed_frozen_fit_record_is_reported_not_an_attribute_error(self):
        self.assertIn("MALFORMED_FROZEN_FIT",cohort_errors([plan("HOLDOUT","h",3)],[None]))
        fit={"fit_at":None,"fit_ids":["c"]};fit["hash"]=digest(fit)
        p=plan("HOLDOUT","h",3);p["calibrator_id"]=fit["hash"];p.pop("id");p["id"]=digest(p)
        self.assertIn("MALFORMED_FROZEN_FIT",cohort_errors([p],[fit]))

    def test_signed_local_ledger_with_bad_fit_ids_is_quarantined_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with closing(Repository(str(root/"seed.sqlite"))) as repo:
                original=create_plan(Service(repo,clock=lambda:NOW),
                    packet([row(100,status="NS",hours=3,score=(None,None))]),
                    {9:"LOWER"},role="CALIBRATION",source_reliability=.95)
            fit={"fit_at":stamp(-48),"fit_ids":"not-an-original-fixture-list"}
            fit["hash"]=digest(fit)
            original.update(role="HOLDOUT",calibrator_id=fit["hash"])
            original.pop("id");original["id"]=digest(original)
            p=root/"malformed-original.sqlite"
            with closing(Repository(str(p))) as repo:
                with repo.transaction():
                    repo.insert("calibrators",fit["hash"],fit,at=fit["fit_at"])
                    repo.record_log("calibrators",fit["hash"],fit["fit_at"],fit)
                    repo.insert("jobs",original["id"],original,at=original["at"])
                    repo.record_log("jobs",original["id"],original["at"],original)
                self.assertTrue(repo.verify())
            before=p.read_bytes();out=audit_originals(p,at=stamp(24))
            self.assertEqual(p.read_bytes(),before)
            self.assertEqual(out["status"],"QUARANTINED")
            self.assertIn("MALFORMED_FROZEN_FIT_IDS",out["cohort_errors"])
            self.assertTrue(all(v is None for v in out["metrics"].values()))
            self.assertFalse(out["holdout_passed"])
            self.assertFalse(out["statistical_profitability_proven"])
