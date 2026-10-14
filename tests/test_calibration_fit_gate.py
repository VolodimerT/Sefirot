"""Calibration fit gate: pure-source contract counterexamples, no real DB."""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys
import sqlite3
from io import StringIO
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sefirot.contracts import Policy, digest
from sefirot.football_provider import HOST
from sefirot.identity import model_code_hash
from sefirot.repository import Repository
from scripts.calibration_fit_gate import assess, main, run

START = datetime(2030, 1, 1, tzinfo=timezone.utc)


def t(days=0, hours=0):
    return (START + timedelta(days=days, hours=hours)).isoformat()


def sign(data):
    data["id"] = digest(data)
    return data


class FakeRepo:
    def __init__(self, **tables):
        self.tables = tables
        self.good = True
        self.model = {
            "model_hash": model_code_hash(),
            "policy_hash": Policy().fingerprint,
        }

    def verify(self):
        return self.good

    def all(self, name, at=None):
        return self.tables.get(name, [])

    def get(self, name, key):
        if name == "model_versions":
            return self.model
        raise ValueError(name)


def fixtures(n):
    receipt_prematch = {
        "provider": "API_FOOTBALL_V3", "provider_host": HOST,
        "endpoint": "/fixtures", "sports_only": True, "http_status": 200,
        "request_started_at": t(hours=8),
        "received_at": t(hours=9),
    }
    receipt_postmatch = {
        "provider": "API_FOOTBALL_V3", "provider_host": HOST,
        "endpoint": "/fixtures", "sports_only": True, "http_status": 200,
        "request_started_at": t(days=3, hours=9),
        "received_at": t(days=3, hours=10),
    }
    plan = sign({
        "schema": "api-forward-plan-v1", "at": t(hours=10),
        "role": "CALIBRATION", "members": [],
    })
    predictions, records, assignments, results = [], [], [], []
    attempts, api_results = [], []
    for i in range(n):
        mid = f"F{i:04d}"
        match = {
            "id": mid, "kickoff": t(days=2, hours=12),
            "competition_profile": "MEN",
        }
        plan["members"].append({"match": match})
        pred = {
            "id": "P-" + mid, "sealed_at": t(hours=11), "sports": {"marker": mid},
            "calibrator": None, "model_id": "model1", "model_hash": model_code_hash(),
            "candidates": [{"key": "1X2:HOME", "raw": [0.6, 0., 0.4],
                            "base": [0.6, 0., 0.4]}],
        }
        predictions.append(pred)
        assignments.append({"match_id": mid, "role": "CALIBRATION", "at": t(hours=10)})
        result = {
            "match_id": mid, "status": "FINISHED",
            "home_goals": 2, "away_goals": 1,
            "finished_at": t(days=2, hours=15),
            "received_at": t(days=3, hours=10),
            "source": "API_FOOTBALL_V3:packet",
        }
        results.append(result)
        api_results.append(result)
        attempts.append({
            "status": "SEALED_RESEARCH", "prediction_id": pred["id"],
            "at": t(hours=10), "sports_hash": digest(pred["sports"]),
            "source_receipts": [receipt_prematch],
        })
        records.append({
            "prediction_id": pred["id"], "match_id": mid,
            "model_id": "model1", "market": "1X2:HOME", "kind": "1X2",
            "model_hash": model_code_hash(), "calibrator_id": None,
            "sealed_at": t(hours=11), "kickoff": match["kickoff"],
            "synthetic": False, "captured_prematch": True,
            "received_at": result["received_at"],
            "raw_probabilities": [0.6, 0., 0.4],
            "probabilities": [0.6, 0., 0.4], "raw_win": 0.6,
            "outcome": "WIN", "competition_profile": "MEN",
        })
    plan["id"] = digest({k:v for k,v in plan.items() if k != "id"})
    capture = sign({
        "schema": "api-forward-capture-v1", "plan_id": plan["id"],
        "at": t(hours=12), "attempts": attempts,
    })
    source_job = sign({
        "schema": "api-forward-result-source-v1", "at": t(days=3, hours=12),
        "receipt": receipt_postmatch, "packet_hash": "packet",
        "api_results": api_results,
    })
    return FakeRepo(jobs=[plan, capture, source_job],
                    calibration_history=records, predictions=predictions,
                    split_assignments=assignments, results=results)


class CalibrationFitGateTests(unittest.TestCase):
    def setUp(self):
        self.model_patch = patch("scripts.calibration_fit_gate._forecast_valid", return_value=True)
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def test_60_original_source_backed_fixtures_ready_to_fit_without_activation(self):
        report = assess(fixtures(60), Policy(), t(days=4))
        self.assertTrue(report["fit_ready"], report["blockers"][:3])
        self.assertEqual(report["record_count"], 60)
        self.assertEqual(report["verified_distinct_matches"], 60)
        self.assertEqual(report["verified_plan_coverage"], 1.)
        self.assertEqual(report["contracts"]["MEN:1X2:HOME"]["populated_bins"], 1)
        self.assertEqual(report["exact_bin_occupancy"]["MEN:1X2:HOME:3"], 60)
        self.assertFalse(report["fit_performed"])
        self.assertFalse(report["model_activated"])
        self.assertFalse(report["monetary_permission"])
        self.assertEqual(report["stake"], 0.)

    def test_less_than_60_games_blocks_fit(self):
        r = assess(fixtures(21), Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertEqual(r["blockers"][-1]["reason"], "INSUFFICIENT_DISTINCT_CALIBRATION_MATCHES")

    def test_unfilled_bin_blocks_model_training(self):
        db = fixtures(60)
        for i, rec in enumerate(db.tables["calibration_history"]):
            rec["raw_win"] = 0.05 + (i % 5) * 0.2
            rec["raw_probabilities"] = [rec["raw_win"], 0, 1 - rec["raw_win"]]
            db.tables["predictions"][i]["candidates"][0]["raw"] = rec["raw_probabilities"]
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertEqual(r["contracts"]["MEN:1X2:HOME"]["populated_bins"], 0)
        self.assertIn("NO_READY_BIN_IN_EVERY_OBSERVED_CONTRACT",
                      [x["reason"] for x in r["blockers"]])

    def test_corrupt_journal_fails_closed(self):
        db = fixtures(60); db.good = False
        with self.assertRaisesRegex(ValueError, "integrity"):
            assess(db, Policy(), t(days=4))

    def test_wrong_settlement_outcome_does_not_train(self):
        db = fixtures(60)
        db.tables["calibration_history"][0]["outcome"] = "LOSS"
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertIn("record probabilities or outcome changed",
                      r["blockers"][0]["reason"])

    def test_no_provenance_blocks_even_with_60_matching_scores(self):
        db = fixtures(60)
        db.tables["jobs"][1]["attempts"][0]["source_receipts"] = []
        db.tables["jobs"][1]["id"] = digest({k:v for k,v in db.tables["jobs"][1].items() if k != "id"})
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertIn("no original source-backed prematch capture proof", r["blockers"][0]["reason"])

    def test_no_records_is_not_calibration_evidence(self):
        db = fixtures(0)
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertEqual(r["verified_distinct_matches"], 0)
        self.assertIn("NO_CALIBRATION_RECORDS", [x["reason"] for x in r["blockers"]])

    def test_synthetic_or_fitted_predictions_not_trainable(self):
        db = fixtures(60); db.tables["calibration_history"][0]["synthetic"] = True
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        db = fixtures(60); db.tables["predictions"][0]["calibrator"] = {"hash":"old"}
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])

    def test_wrong_original_role_blocks(self):
        db = fixtures(60); db.tables["jobs"][0]["role"] = "HOLDOUT"
        db.tables["jobs"][0]["id"] = digest({k:v for k,v in db.tables["jobs"][0].items() if k != "id"})
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertIn("no original calibration plan", r["blockers"][0]["reason"])

    def test_missing_local_db_does_not_create_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing.sqlite"
            with self.assertRaisesRegex(ValueError, "existing research ledger"):
                run(target, output=Path(directory)/"audit.json", fit=True)
            self.assertFalse(target.exists())

    def test_model_mismatch_stops_calibration(self):
        db = fixtures(60); db.model["policy_hash"] = "different"
        r = assess(db, Policy(), t(days=4))
        self.assertFalse(r["fit_ready"])
        self.assertIn("Policy cannot fit", str(r["blockers"]))

    def add_cohort(self, db, role, mid, *, kickoff_day=1, fit=None):
        plan = {"schema": "api-forward-plan-v1", "at": t(hours=8),
                "role": role, "members": [{"match": {
                    "id": mid, "kickoff": t(days=kickoff_day, hours=12),
                    "competition_profile": "MEN"}}]}
        if fit is not None:
            plan["calibrator_id"] = fit["hash"]
            db.tables.setdefault("calibrators", []).append(fit)
        db.tables["jobs"].append(sign(plan))

    def test_cross_cohort_fixture_blocks_otherwise_ready_fit(self):
        db = fixtures(60)
        self.add_cohort(db, "TRAIN", "F0000")
        report = assess(db, Policy(), t(days=4))
        self.assertFalse(report["fit_ready"])
        self.assertEqual(report["verified_distinct_matches"], 60)
        self.assertIn("DUPLICATE_OR_CROSS_COHORT_FIXTURE",
                      [b["reason"] for b in report["blockers"]])

    def test_train_after_calibration_blocks_even_for_disjoint_fixture_ids(self):
        db = fixtures(60)
        self.add_cohort(db, "TRAIN", "different-training-fixture", kickoff_day=3)
        report = assess(db, Policy(), t(days=4))
        self.assertFalse(report["fit_ready"])
        self.assertIn("COHORT_TIME_WINDOWS_OVERLAP",
                      [b["reason"] for b in report["blockers"]])

    def test_previously_seen_test_cannot_be_ignored_by_fit_preflight(self):
        db = fixtures(60)
        self.add_cohort(db, "TEST", "already-viewed-fixture")
        report = assess(db, Policy(), t(days=4))
        self.assertFalse(report["fit_ready"])
        self.assertIn("UNKNOWN_COHORT_ROLE", [b["reason"] for b in report["blockers"]])

    def test_holdout_original_fit_overlap_blocks_training_preflight(self):
        db = fixtures(60)
        fit = {"fit_at": t(hours=5), "fit_ids": ["holdout-fixture"]}
        fit["hash"] = digest(fit)
        self.add_cohort(db, "HOLDOUT", "holdout-fixture", kickoff_day=3, fit=fit)
        report = assess(db, Policy(), t(days=4))
        self.assertFalse(report["fit_ready"])
        self.assertIn("HOLDOUT_OVERLAPS_FIT_IDS", [b["reason"] for b in report["blockers"]])

    def test_distinct_historical_train_and_calibration_remain_ready_without_fit(self):
        db = fixtures(60)
        self.add_cohort(db, "TRAIN", "different-training-fixture")
        before = deepcopy(db.tables)
        report = assess(db, Policy(), t(days=4))
        self.assertTrue(report["fit_ready"], report["blockers"])
        self.assertEqual(report["cohort_errors"], [])
        self.assertEqual(db.tables, before)
        self.assertFalse(report["fit_performed"])
        self.assertFalse(report["monetary_permission"])
        self.assertEqual(report["stake"], 0)


class CalibrationFitTransactionTests(unittest.TestCase):
    """Two real SQLite connections; only assessment and fitting are synthetic."""

    def ready(self, count=60):
        report = {"fit_ready": True, "fit_model_id": "synthetic-model",
                  "record_count": count, "verified_distinct_matches": count,
                  "planned_distinct_matches": count, "fit_performed": False,
                  "model_activated": False, "monetary_permission": False,
                  "stake": 0}
        report["hash"] = digest(report)
        return report

    def append_job(self, repo):
        record = {"schema": "synthetic-concurrent-input", "at": t()}
        identifier = digest(record)
        record["id"] = identifier
        with repo.transaction():
            repo.insert("jobs", identifier, record, at=t())
            repo.record_log("jobs", identifier, t(), record)

    def test_read_only_preflight_keeps_verified_wal_snapshot_during_valid_append(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "synthetic.sqlite"
            writer = Repository(db)
            try:
                writer.db.execute("PRAGMA journal_mode=WAL")
                observed = []

                def inspect(repo, policy, at):
                    self.assertTrue(repo.verify())
                    self.append_job(writer)
                    observed.append(len(repo.all("jobs")))
                    return self.ready()

                with patch("scripts.calibration_fit_gate.assess", side_effect=inspect):
                    run(db, output=Path(directory) / "preflight.json")
                self.assertEqual(observed, [0], "assessment mixed verified and newer rows")
                self.assertEqual(len(writer.all("jobs")), 1)
                self.assertTrue(writer.verify())
                self.assertEqual(writer.all("calibrators"), [])
            finally:
                writer.close()

    def test_competing_writer_cannot_change_inputs_between_recheck_and_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "synthetic.sqlite"
            writer = Repository(db)
            try:
                writer.db.execute("PRAGMA busy_timeout=0")
                competed = []

                def fit(service, at):
                    try:
                        self.append_job(writer)
                    except sqlite3.OperationalError as exc:
                        self.assertIn("locked", str(exc))
                        competed.append("BLOCKED")
                    else:
                        competed.append("APPENDED")
                    self.assertEqual(service.repo.all("jobs"), [])
                    artifact = {"synthetic": True, "fit_ids": [], "fit_at": at}
                    artifact["hash"] = digest(artifact)
                    with service.repo.transaction():
                        service.repo.insert("calibrators", artifact["hash"], artifact, at=at)
                        service.repo.record_log("calibrators", artifact["hash"], at, artifact)
                    return artifact

                with patch("scripts.calibration_fit_gate.assess", side_effect=[self.ready(), self.ready()]), \
                        patch("scripts.calibration_fit_gate.Service.calibrate", autospec=True, side_effect=fit):
                    report = run(db, output=Path(directory) / "fit.json", fit=True)
                self.assertEqual(competed, ["BLOCKED"])
                self.assertTrue(report["fit_performed"])
                self.assertTrue(writer.verify())
                self.assertEqual(len(writer.all("calibrators")), 1)
                self.assertFalse(report["monetary_permission"])
                self.assertEqual(report["stake"], 0)
            finally:
                writer.close()

    def test_fit_report_describes_locked_fresh_inputs_instead_of_old_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "synthetic.sqlite"
            Repository(db).close()
            artifact = {"hash": "synthetic-fit", "synthetic": True}
            with patch("scripts.calibration_fit_gate.assess", side_effect=[self.ready(60), self.ready(61)]), \
                    patch("scripts.calibration_fit_gate.Service.calibrate", return_value=artifact):
                report = run(db, output=Path(directory) / "fit.json", fit=True)
            self.assertEqual(report["record_count"], 61)
            self.assertEqual(report["verified_distinct_matches"], 61)
            self.assertEqual(report["planned_distinct_matches"], 61)
            signature = report.pop("hash")
            self.assertEqual(signature, digest(report))

    def test_cli_reports_sqlite_lock_failure_without_traceback_or_retry(self):
        error = StringIO()
        with patch("scripts.calibration_fit_gate.run", side_effect=sqlite3.OperationalError("database is locked")) as call, \
                redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            main(["--db", "synthetic.sqlite", "--output", "synthetic.json"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("Calibration fit gate: database is locked", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())
        call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
