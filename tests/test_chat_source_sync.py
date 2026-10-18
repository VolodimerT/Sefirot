"""Opt-in source QC bootstrap never fetches upstream sports or mutates CORE."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import chat_source_sync as source_qc

ACTIVE = {
    "SEFIROT_SOURCE_RESEARCH_SYNC": "1",
    "SEFIROT_SOURCE_ARCHIVE": "1",
    "SEFIROT_BRIDGE_READ_ONLY": "1",
    "SEFIROT_CHAT_JOB_WORKER_MODE": "sports_probe",
}


def view():
    return {
        "expected_matches": 380, "calendar_complete": True,
        "observed_matches": 68, "confirmed_ft": 68,
        "statistics_qc_matches": 1, "qc_rejected_packets": 0,
        "pending_qc_packets": 0,
    }


class SourceQcBootstrapTests(unittest.TestCase):
    def test_disabled_is_inert(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(source_qc, "sync_archive") as relay:
            report = source_qc.bootstrap(Path("/tmp/unused-sefirot-source.sqlite"))
        self.assertEqual(report["status"], "DISABLED")
        relay.assert_not_called()

    def test_only_sportrunner_archive_readonly_mode_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {**ACTIVE, "SEFIROT_BRIDGE_READ_ONLY": "0"}), patch.object(source_qc, "sync_archive") as relay:
                report = source_qc.bootstrap(Path(folder) / "source.sqlite")
            self.assertEqual(report["status"], "MODE_GUARD_STOP")
            relay.assert_not_called()

    def test_bounded_export_import_and_coverage_are_research_only(self):
        with tempfile.TemporaryDirectory() as folder:
            source_path=Path(folder)/"source.sqlite"
            pages=[
                {"complete":False,"added_sources":2,"next_after":"a"*64},
                {"complete":True,"added_sources":1,"next_after":""},
            ]
            calls=[]
            def fake_sync(repo,*,after,limit):
                self.assertTrue(repo.verify())
                calls.append((after,limit))
                return pages[len(calls)-1]
            with patch.dict(os.environ, ACTIVE), patch.object(source_qc,"sync_archive",side_effect=fake_sync) as sync, patch.object(source_qc,"league_view",return_value=view()) as coverage:
                result=source_qc.bootstrap(source_path)
            self.assertEqual(result["status"],"SOURCE_QC_COMPLETE")
            self.assertEqual(result["new_local_sources"],3)
            self.assertEqual(result["provider_requests"],0)
            self.assertIsNone(result["model_probability"])
            self.assertFalse(result["monetary_permission"])
            self.assertFalse(result["calibration_fit_allowed"])
            self.assertEqual(result["league_coverage"]["39"]["expected_matches"],380)
            self.assertEqual(calls,[("",100),("a"*64,100)])
            self.assertEqual(sync.call_count,2)
            self.assertEqual(coverage.call_count,3)
            if os.name!="nt":
                self.assertEqual(source_path.stat().st_mode & 0o777,0o600)

    def test_incomplete_page_bound_does_not_claim_full_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            page={"complete":False,"added_sources":1,"next_after":"b"*64}
            with patch.dict(os.environ,ACTIVE),patch.object(source_qc,"sync_archive",return_value=page),patch.object(source_qc,"league_view") as coverage:
                result=source_qc.bootstrap(Path(folder)/"source.sqlite")
            self.assertEqual(result["status"],"SOURCE_SYNC_PAGE_CAP")
            self.assertFalse(result["complete"])
            self.assertEqual(result["provider_requests"],0)
            coverage.assert_not_called()


if __name__=="__main__":
    unittest.main()
