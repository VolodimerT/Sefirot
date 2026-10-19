"""Private source SQL permission/archive/planner proof on isolated PostgreSQL."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]

class FootballSourceSQLTests(unittest.TestCase):
    def test_append_only_archive_acl_binding_and_global_daily_cap(self):
        run=subprocess.run([shutil.which('node') or 'node','scripts/test_football_source_store.mjs'],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout),{'groups':6,'source':'SYNTHETIC_ONLY'})
