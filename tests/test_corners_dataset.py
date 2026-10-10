"""Synthetic contract tests, never evidence of corner prediction edge."""
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from sefirot.corners_dataset import load_footiqo_csv,coverage_report
from sefirot.corners_shadow import fit

NOW=datetime(2026,10,10,21,tzinfo=timezone.utc)
HEAD="id,matchDate,Season,homeTeam,awayTeam,HCFT,ACFT,HC1H,AC1H,HC2H,AC2H\n"
ROWS=("11,05-10-26 15:00,2026,Junior,Inter Bogota,5,3,2,1,3,2\n"
      "12,06-10-26 15:00,2026,Inter Bogota,Junior,4,7,3,4,1,3\n")

def load(payload=HEAD+ROWS,partial=False):
    with tempfile.TemporaryDirectory() as d:
        file=Path(d)/"corners.csv"
        file.write_text(payload,encoding="utf-8")
        return load_footiqo_csv(file,acquired_at=NOW,fixture_timezone="UTC",
                                league="COL-PRIMERA-A",allow_partial=partial)

class FeedTests(unittest.TestCase):
    def test_valid_file_keeps_source_and_delayed_timestamp(self):
        x=load()
        self.assertEqual(len(x.rows),2)
        self.assertTrue(x.content_sha256)
        self.assertEqual(x.rows[0].available_at,NOW)
        self.assertIn("ARCHIVED_NOT_HISTORICALLY_SEALED",x.statuses)
        self.assertFalse(x.monetary_permission)

    def test_missing_half_columns_rejected(self):
        with self.assertRaisesRegex(ValueError,"missing required"):
            load("id,matchDate,Season,homeTeam,awayTeam,HCFT,ACFT\n11,05-10-26 15:00,2026,A,B,4,5\n")

    def test_inconsistent_corners_rejected(self):
        with self.assertRaisesRegex(ValueError,"FT != 1H"):
            load(HEAD+"11,05-10-26 15:00,2026,A,B,4,5,2,1,3,4\n")

    def test_fails_if_fixture_time_unknown_or_future(self):
        with self.assertRaisesRegex(ValueError,"future or unfinished"):
            load(HEAD+"11,12-10-26 15:00,2026,A,B,4,5,2,1,2,4\n")
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"file.csv";file.write_text(HEAD+ROWS)
            with self.assertRaisesRegex(ValueError,"unknown fixture timezone"):
                load_footiqo_csv(file,acquired_at=NOW,fixture_timezone="Moon/Sea",league="COL-A")

    def test_fails_on_duplicate_fixture_id(self):
        with self.assertRaisesRegex(ValueError,"duplicate fixture ID"):
            load(HEAD+ROWS+"11,07-10-26 15:00,2026,A,C,4,4,2,2,2,2\n",True)

    def test_partial_only_with_explicit_flag(self):
        invalid=HEAD+ROWS+"13,07-10-26 15:00,2026,A,C,missing,4,2,2,2,2\n"
        with self.assertRaises(ValueError): load(invalid)
        x=load(invalid,True)
        self.assertEqual(len(x.rows),2)
        self.assertEqual(len(x.dropped),1)

    def test_coverage_requires_independent_complete_manifest(self):
        x=load()
        self.assertEqual(coverage_report(x.rows,expected=None)["status"],"COVERAGE_UNKNOWN")
        ids={x.fixture_id for x in x.rows}
        self.assertEqual(coverage_report(x.rows,expected=ids)["status"],"INCOMPLETE_OR_UNLICENSED")
        self.assertEqual(coverage_report(x.rows,expected=ids,source_accepted=True)["status"],"RESEARCH_DATA_READY")
        rep=coverage_report(x.rows,expected=ids|{"other"},source_accepted=True)
        self.assertEqual(rep["status"],"INCOMPLETE_OR_UNLICENSED")
        self.assertEqual(len(rep["missing_ids"]),1)

    def test_archive_cannot_backfill_prior_historical_predictions(self):
        x=load()
        with self.assertRaisesRegex(ValueError,"future/unavailable"):
            fit(x.rows,league="COL-PRIMERA-A",home="Junior",away="Inter Bogota",
                as_of=datetime(2026,10,7,tzinfo=timezone.utc),
                kickoff=datetime(2026,10,8,tzinfo=timezone.utc),min_league=10,min_team=1)

if __name__=="__main__":unittest.main()
