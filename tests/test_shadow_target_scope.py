"""Owned source packets exercise the existing source -> CORE route without I/O."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import football_pipeline as pipeline
from research import shadow_model as shadow
from sefirot.contracts import canonical, digest
from sefirot.repository import Repository
from sefirot.markets import DEFAULT_POOL
from sefirot.service import Service


class ShadowTargetScopeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.repo = Repository(Path(self.folder.name) / "owned-source.sqlite")
        self.addCleanup(self.repo.close)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.cutoff = (self.now - timedelta(minutes=1)).isoformat()
        self.rows = [self.fixture(n, "FT") for n in range(1, 9)] + [self.fixture(9001, "NS")]

    def fixture(self, fid, status):
        kickoff = self.now + timedelta(hours=2) if status == "NS" else self.now - timedelta(days=10 + fid)
        return {"fixture": {"id": fid, "date": kickoff.isoformat(),
                "status": {"short": status, "elapsed": 90 if status == "FT" else None}},
                "league": {"id": 39, "season": 2026, "type": "League"},
                "teams": {"home": {"id": 1, "name": "Owned Alpha"},
                          "away": {"id": 2, "name": "Owned Beta"}},
                "score": {"fulltime": {"home": 2 if status == "FT" else None,
                                       "away": 1 if status == "FT" else None}}}

    def packet(self, params=None):
        params = params or {"league": 39, "season": 2026}
        data = {"get": "fixtures", "parameters": {k: str(v) for k, v in params.items()},
                "errors": [], "results": len(self.rows), "paging": {"current": 1, "total": 1},
                "response": deepcopy(self.rows)}
        return {"data": data, "receipt": {"provider": "API_FOOTBALL_V3",
                "provider_host": "v3.football.api-sports.io", "endpoint": "/fixtures",
                "parameters": params, "request_started_at": self.cutoff,
                "received_at": self.cutoff, "upstream_received_at": self.cutoff,
                "http_status": 200, "sports_only": True, "transport": "SUPABASE_GATEWAY",
                "payload_hash": digest(data)}}

    def put(self, packet):
        return pipeline.ingest(self.repo, canonical(packet).encode(), imported_at=self.cutoff)

    def test_explicit_target_reaches_real_core_without_other_league_calendars(self):
        self.assertTrue(self.put(self.packet())["accepted"])
        originals = deepcopy(self.repo.all("jobs"))
        with patch("scripts.chat_sports_probe.get_sports") as provider:
            result = shadow.preview(self.repo, as_of=self.cutoff, ids=[9001])
        provider.assert_not_called()
        self.assertEqual(result["status"], "SHADOW_PREVIEW_COMPLETE")
        self.assertEqual(result["inputs_evaluated"], 1)
        row = result["previews"][0]
        self.assertEqual(row["status"], "UNVALIDATED_SHADOW")
        self.assertEqual(row["team_history_games"], [8, 8])
        self.assertTrue(row["markets"])
        for market in row["markets"]:
            self.assertAlmostEqual(sum(market[key] for key in ("raw_win", "raw_push", "raw_loss")), 1)
        self.assertEqual(row["decision"], "PASS")
        self.assertEqual(row["stake"], 0)
        self.assertIsNone(row["ev"])
        self.assertFalse(result["monetary_permission"])
        self.assertFalse(result["probability_calibrated"])
        self.assertEqual(result["canonical_predictions_written"], 0)
        self.assertEqual(self.repo.all("jobs"), originals)
        self.assertEqual(self.repo.all("predictions"), [])
        self.assertEqual(self.repo.all("split_assignments"), [])

    def test_selected_league_still_requires_its_own_full_calendar(self):
        self.assertTrue(self.put(self.packet({"league": 39, "season": 2026,
                                             "from": "2026-01-01", "to": "2027-12-31"}))["accepted"])
        with patch.object(shadow, "prepare") as engine:
            result = shadow.preview(self.repo, as_of=self.cutoff, ids=[9001])
        engine.assert_not_called()
        self.assertEqual(result["status"], "SHADOW_SOURCE_QC_STOP")
        self.assertEqual(result["league"], 39)

    def test_any_existing_rejected_source_still_stops_selected_preview(self):
        self.put(self.packet())
        bad = self.packet()
        bad["receipt"]["payload_hash"] = "a" * 64
        self.assertFalse(self.put(bad)["accepted"])
        with patch.object(shadow, "prepare") as engine:
            result = shadow.preview(self.repo, as_of=self.cutoff, ids=[9001])
        engine.assert_not_called()
        self.assertEqual(result["status"], "SHADOW_SOURCE_QC_STOP")

    def test_source_inputs_can_use_existing_capture_without_an_alternative_engine(self):
        self.put(self.packet())
        originals = deepcopy(self.repo.all("jobs"))
        inputs = pipeline.model_inputs(self.repo, 9001, as_of=self.cutoff,
                                       profile="MEN", source_reliability=.8)
        sports = deepcopy(inputs["main"]["sports"])
        sports["synthetic"] = True  # Owned test packets are never real training evidence.
        prediction_repo = Repository(Path(self.folder.name) / "owned-predictions.sqlite")
        self.addCleanup(prediction_repo.close)
        service = Service(prediction_repo, clock=lambda: self.now)
        seal = service.capture(sports, DEFAULT_POOL)
        self.assertTrue(seal["synthetic"])
        self.assertTrue(seal["captured_prematch"])
        self.assertFalse(seal["reconstructed"])
        self.assertEqual(seal["sports"], sports)
        self.assertEqual(canonical(prediction_repo.all("predictions")), canonical([seal]))
        self.assertEqual(canonical(service.capture(sports, DEFAULT_POOL)), canonical(seal))
        self.assertEqual(len(prediction_repo.all("predictions")), 1)
        self.assertEqual(prediction_repo.all("split_assignments"), [])
        self.assertEqual(prediction_repo.all("calibrators"), [])
        self.assertEqual(prediction_repo.all("decisions"), [])
        self.assertEqual(prediction_repo.all("bets"), [])
        self.assertEqual(self.repo.all("jobs"), originals)
        self.assertTrue(prediction_repo.verify())


if __name__ == "__main__":
    unittest.main()
