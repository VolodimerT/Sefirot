"""Synthetic integration and adversarial boundaries, no network/source attestation."""
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from sefirot.contracts import digest, time
from sefirot.repository import Repository
from sefirot.stake_mapper import normalize_snapshot
from research.prematch_readiness import operator_report
from research.prematch_scenario import FIXTURES, run_scenario
from research.chat_answer_contract import AnswerError, validate_answer
from test_stake_mapper import snapshot


class StakeScopeRegressionTests(unittest.TestCase):
    def test_half_extra_time_unknown_group_or_specifiers_do_not_become_ft(self):
        for index in (0, 1, 3, 4):
            for scope in ("period=1H", "period=2H", "period=ET", "period=UNKNOWN"):
                with self.subTest(index=index, scope=scope):
                    s = snapshot(); m = s["markets"][index]
                    m["specifiers"] = (m["specifiers"] + "|" + scope).strip("|")
                    s["markets"] = [m]
                    out = normalize_snapshot(s)
                    self.assertEqual(out["main_quotes"], [])
                    self.assertIn("MAIN_SCOPE_UNVERIFIED", [r["reason"] for r in out["rejected"]])
        for group in ("1st Half", "Extra Time", "UNKNOWN", None):
            s = snapshot(); s["markets"] = [s["markets"][0]]; s["markets"][0]["group"] = group
            self.assertEqual(normalize_snapshot(s)["main_quotes"], [])

    def test_1x2_duplicate_different_ids_is_not_a_complete_partition(self):
        s = snapshot(); s["markets"] = [s["markets"][0]]
        s["markets"][0]["outcomes"][2]["name"] = s["home"]
        out = normalize_snapshot(s)
        self.assertEqual(out["main_quotes"], [])
        self.assertEqual(out["rejected"][0]["reason"], "INVALID_1X2_PARTITION")

    def test_double_chance_duplicate_is_not_complete(self):
        s = snapshot(); s["markets"] = [s["markets"][4]]
        s["markets"][0]["outcomes"][2]["name"] = s["markets"][0]["outcomes"][0]["name"]
        self.assertEqual(normalize_snapshot(s)["main_quotes"], [])

    def test_total_text_line_and_specifier_must_agree(self):
        for name in ("Over 3.5", "Over 2.5 first half", "Over 2.50 bad"):
            s = snapshot(); s["markets"] = [s["markets"][1]]
            s["markets"][0]["outcomes"][0]["name"] = name
            self.assertEqual(normalize_snapshot(s)["main_quotes"], [])

    def test_same_total_side_twice_or_wrong_handicap_sign_is_rejected(self):
        s = snapshot(); s["markets"] = [s["markets"][1]]
        s["markets"][0]["outcomes"][1]["name"] = "Over 2.5"
        self.assertEqual(normalize_snapshot(s)["main_quotes"], [])
        s = snapshot(); s["markets"] = [s["markets"][3]]
        s["markets"][0]["outcomes"][1]["name"] = s["away"] + " (-1)"
        self.assertEqual(normalize_snapshot(s)["main_quotes"], [])

    def test_dnb_and_btts_require_distinct_partition(self):
        for template, names in (("Draw No Bet", ("Cyprus", "Cyprus")),
                                ("Both Teams to Score", ("Yes", "Yes"))):
            s = snapshot(); s["markets"] = [{"id":"synthetic","group":"main",
                "template":template,"name":template,"specifiers":"",
                "outcomes":[{"id":str(i),"name":n,"odds":2.} for i,n in enumerate(names)]}]
            self.assertEqual(normalize_snapshot(s)["main_quotes"], [])


class PrematchPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture"
        shutil.copytree(FIXTURES, self.fixture)

    def change(self, name, mutation):
        p = self.fixture / name
        value = json.loads(p.read_text())
        mutation(value)
        if name == "source.json":
            for packet in value["packets"]:
                packet["receipt"]["payload_hash"] = digest(packet["data"])
        value.pop("hash"); value["hash"] = digest(value)
        p.write_text(json.dumps(value))

    def run_case(self):
        return run_scenario(fixture_directory=self.fixture, work_directory=self.root / "work")

    def test_one_original_path_replay_chat_audit_and_zero_tickets(self):
        before = {p.name:p.read_bytes() for p in self.fixture.iterdir()}
        with patch("socket.socket", side_effect=AssertionError("NETWORK_FORBIDDEN")):
            report = self.run_case()
        self.assertTrue(report["ledger_integrity"])
        self.assertTrue(report["replay_matches"])
        self.assertEqual(report["source_adapter_training_rows"], 0)
        self.assertEqual(report["truth_levels"]["CORE_PASS"]["core_decision"], "PASS")
        self.assertEqual(report["truth_levels"]["CORE_PASS"]["core_class"], "D")
        self.assertIsNone(report["truth_levels"]["CORE_BET"])
        self.assertIsNone(report["truth_levels"]["OUR_TICKET"])
        self.assertFalse(report["truth_levels"]["BOOKMAKER_QUOTE_OBSERVED"]["verified_real"])
        self.assertEqual(report["duplicate_status"], ["ALREADY_PROCESSED"] * 2)
        self.assertEqual(report["stake"], 0)
        self.assertIn("СИНТЕТИЧЕСКИЙ", report["chat_text"])
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.fixture.iterdir()})
        self.assertEqual(len(report["operator"]["original_decisions"]), 1)

    def test_price_bytes_first_open_only_after_original_seal(self):
        import research.prematch_scenario as module
        original = module._frozen
        observations = []
        def read(path, schema):
            if path.name == "price.json":
                with closing(Repository(str(self.root / "work" / "scenario.sqlite"), read_only=True)) as repo:
                    observations.append(len(repo.all("predictions")))
            return original(path, schema)
        with patch.object(module, "_frozen", side_effect=read):
            self.run_case()
        self.assertEqual(observations, [1])

    def test_wrong_fixture_status_and_late_source_are_closed(self):
        changes = [
            lambda s:s.update(fixture_id=999999),
            lambda s:s["packets"][0]["data"]["response"][0]["fixture"]["status"].update(short="1H"),
            lambda s:s["packets"][0]["receipt"].update(received_at="2030-01-01T13:00:00+00:00"),
            lambda s:s.update(capture_at="2030-01-01T12:01:00+00:00")]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                shutil.rmtree(self.fixture);shutil.copytree(FIXTURES,self.fixture)
                if (self.root/"work").exists():shutil.rmtree(self.root/"work")
                self.change("source.json",change)
                with self.assertRaises(ValueError):self.run_case()

    def test_wrong_quote_fixture_period_and_settlement_are_closed(self):
        changes = [
            lambda p:p["event"]["competitors"].reverse(),
            lambda p:p["markets"][0].update(specifiers="period=1H"),
            lambda p:p.update(rules_evidence="UNKNOWN")]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                shutil.rmtree(self.fixture);shutil.copytree(FIXTURES,self.fixture)
                if (self.root/"work").exists():shutil.rmtree(self.root/"work")
                self.change("price.json",change)
                with self.assertRaises(ValueError):self.run_case()

    def test_missing_sources_and_unverified_calibration_stay_pass(self):
        r = self.run_case()
        blockers = r["truth_levels"]["CORE_PASS"]["missing_data"]
        self.assertIn("CALIBRATION_INSUFFICIENT",blockers)
        self.assertIn("HOLDOUT_UNVALIDATED",blockers)
        self.assertTrue(r["coverage"]["blockers"])
        self.assertEqual(r["truth_levels"]["CORE_PASS"]["core_decision"],"PASS")

    def test_exhausted_or_unknown_gateway_quota_refuses_before_any_seal(self):
        for reason in ("BUDGET_EXHAUSTED", "QUOTA_UNKNOWN"):
            with self.subTest(reason=reason):
                shutil.rmtree(self.fixture);shutil.copytree(FIXTURES,self.fixture)
                if (self.root/"work").exists():shutil.rmtree(self.root/"work")
                self.change("source.json",lambda s:s["gateway_contract"].update(ok=False,error=reason))
                with self.assertRaises(ValueError):self.run_case()
                self.assertFalse((self.root/"work"/"scenario.sqlite").exists())

    def test_missing_shared_budget_marker_refuses_before_any_seal(self):
        self.change("source.json",lambda s:s["gateway_contract"].pop("shared_budget_guard"))
        with self.assertRaises(ValueError):self.run_case()
        self.assertFalse((self.root/"work"/"scenario.sqlite").exists())

    def test_stale_quote_stays_pass_with_price_blocker(self):
        self.change("source.json",lambda s:s.update(decision_at="2030-01-01T09:10:00+00:00"))
        r=self.run_case()
        self.assertIn("PRICE_STALE",r["truth_levels"]["CORE_PASS"]["missing_data"])
        self.assertEqual(r["truth_levels"]["CORE_PASS"]["core_decision"],"PASS")

    def test_changed_sql_metadata_blocks_operator_and_chat(self):
        r=self.run_case(); db=self.root/"work"/"scenario.sqlite"
        with sqlite3.connect(db) as connection:
            connection.execute("DROP TRIGGER decisions_no_update")
            connection.execute("UPDATE decisions SET at='2030-01-01T09:03:00+00:00'")
        out=operator_report(db,at="2030-01-01T09:10:00+00:00")
        self.assertEqual(out["ledger_status"],"INTEGRITY_FAILED")
        self.assertEqual(out["original_decisions"],[])
        with closing(Repository(str(db),read_only=True)) as repo:
            with self.assertRaises(AnswerError):
                validate_answer(r["truth_levels"]["CORE_PASS"],expected_fixtures=[
                    r["truth_levels"]["CORE_PASS"]["fixture_id"]],
                    at=time("2030-01-01T09:10:00+00:00"),repo=repo,archive=True)

    def test_readonly_report_does_not_create_absent_db_or_change_existing_bytes(self):
        missing=self.root/"missing"/"absent.sqlite"
        self.assertEqual(operator_report(missing)["ledger_status"],"ABSENT")
        self.assertFalse(missing.parent.exists())
        self.run_case(); db=self.root/"work"/"scenario.sqlite"; before=db.read_bytes()
        out=operator_report(db,at="2030-01-01T09:02:00+00:00")
        self.assertEqual(db.read_bytes(),before)
        self.assertEqual(out["forecasts_created"],0)
        self.assertTrue(all(s["status"]=="NOT_VERIFIED" and s["quota"] is None
                            for s in out["sources"].values()))

    def test_no_data_is_unavailable_without_synthetic_forecast(self):
        out=operator_report(at="2030-01-01T09:00:00+00:00")
        self.assertEqual(out["original_decisions"],[])
        self.assertEqual(out["readiness"],[])
        self.assertEqual(out["ledger_status"],"NOT_SUPPLIED")

    def test_after_kickoff_only_original_archive_remains_and_window_is_closed(self):
        self.run_case()
        out=operator_report(self.root/"work"/"scenario.sqlite",at="2030-01-01T13:00:00+00:00")
        self.assertEqual(out["readiness"][0]["status"],"PREMATCH_CLOSED")
        self.assertEqual(out["original_decisions"][0]["core_decision"],"PASS")
        self.assertEqual(out["original_decisions"][0]["phase_source"],"ORIGINAL_LEDGER_ARCHIVE")
