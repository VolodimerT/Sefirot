"""Run the actual server handler's offline auth/transport counterexamples."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServerGatewayTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for the JavaScript gateway contract suite')
    def test_actual_gateway_handler_auth_transport_and_error_contracts(self):
        result = subprocess.run(['node', str(ROOT / 'scripts/test_sports_gateway.mjs')],
                                cwd=ROOT, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('GATEWAY_CONTRACTS_PASSED=41', result.stdout)
        from sefirot.contracts import canonical
        line=next(v for v in result.stdout.splitlines() if v.startswith('SOURCE_CANONICAL_VECTORS='))
        for vector in json.loads(line.split('=',1)[1]):
            self.assertEqual(vector['canonical'],canonical(json.loads(vector['wire'])))


if __name__ == '__main__':
    unittest.main()
