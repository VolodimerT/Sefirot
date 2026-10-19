"""SQL resume guards on owned PostgreSQL; no hosted operations."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESUME = 'supabase/migrations/20261017114454_resume_probe_worker.sql'


class ProbeResumeSQLTests(unittest.TestCase):
    def test_guarded_resume_preserves_rows_budget_and_fences(self):
        run = subprocess.run([shutil.which('node') or 'node', 'scripts/test_probe_resume.mjs'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), {'groups': 10, 'source': 'SYNTHETIC_ONLY'})
