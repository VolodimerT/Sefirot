"""Real 7500/day SQL budget is exercised in a disposable PGlite database."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ProQuota7500Tests(unittest.TestCase):
    def test_daily_quota_owner_acl_dispatch_and_no_counter_reset(self):
        result=subprocess.run(
            [shutil.which('node') or 'node','scripts/test_pro_budget_7500.mjs'],
            cwd=ROOT,text=True,encoding='utf-8',capture_output=True,timeout=90)
        self.assertEqual(result.returncode,0,
                         (result.stdout+'\n'+result.stderr)[-4500:])
        data=json.loads(result.stdout)
        self.assertEqual(data,{'pro_quota_contract':'PASS','daily_limit':7500,
                               'rate_limit':60,'attempts_not_reset':True,'provider_calls':0})

if __name__=='__main__':
    unittest.main()
