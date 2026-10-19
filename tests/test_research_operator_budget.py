"""Actual operator arm SQL in isolated PostgreSQL WASM; not a production arm."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
class ResearchOperatorBudgetTests(unittest.TestCase):
    def test_actual_arm_sql_bounds_daily_cap_minute_history_and_acl(self):
        r=subprocess.run([shutil.which('node') or 'node','scripts/test_research_operator_budget.mjs'],cwd=ROOT,
                         text=True,encoding='utf-8',capture_output=True,timeout=60)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout),{'operator_contract':'PASS','provider_calls':0,'source':'SYNTHETIC_ONLY'})
