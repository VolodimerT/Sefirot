"""Boundary regressions for one entrypoint and the default daily workflow."""
import io
import json
from contextlib import closing, redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sefirot.cli import main
from sefirot.contracts import Policy
from sefirot.identity import code_hash, model_code_hash
from sefirot.repository import Repository


class StabilityBoundaryTests(unittest.TestCase):
    def invoke(self, *arguments, cwd=None, launcher='sefirot.py'):
        return subprocess.run([sys.executable, str(ROOT/launcher), *arguments],
                              cwd=cwd or ROOT, capture_output=True, encoding='utf-8')

    def test_help_and_build_identity_never_create_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary)/'missing.sqlite'
            for arguments in (('--db', str(missing), '--help'),
                              ('--db', str(missing), '--labs', '--help'),
                              ('--db', str(missing), 'build-info')):
                result = self.invoke(*arguments, cwd=temporary)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_default_help_limits_surface_but_full_help_preserves_commands(self):
        lean = self.invoke('--help'); labs = self.invoke('--labs', '--help')
        self.assertEqual(lean.returncode, 0); self.assertEqual(labs.returncode, 0)
        for command in ('builder-grid', 'small-market-review', 'sync-supabase', 'activate'):
            self.assertNotIn(command, lean.stdout)
            self.assertIn(command, labs.stdout)
        self.assertIn('forward-scorecard', lean.stdout)
        self.assertIn('work', lean.stdout)
        self.assertNotIn('api-health', lean.stdout)
        self.assertIn('api-health', labs.stdout)

    def test_verify_refuses_missing_database_and_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary)/'missing'/'ledger.sqlite'
            result = self.invoke('--db', str(database), 'verify')
            self.assertEqual(result.returncode, 2)
            self.assertFalse(database.parent.exists())
            database = Path(temporary)/'existing.sqlite'
            with closing(Repository(database)) as repo:
                repo.log('TEST_CHECK', '2030-01-01T00:00:00+00:00', {'synthetic': True})
            before = database.read_bytes()
            result = self.invoke('--db', str(database), 'verify')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['integrity'])
            self.assertEqual(database.read_bytes(), before)

    def test_verify_corrupt_journal_returns_failure_without_repair(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary)/'existing.sqlite'
            with closing(Repository(database)) as repo:
                repo.log('TEST_CHECK', '2030-01-01T00:00:00+00:00', {'synthetic': True})
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute('DROP TRIGGER audit_logs_no_update')
                    connection.execute("UPDATE audit_logs SET payload='{}'")
            before = database.read_bytes()
            result = self.invoke('--db', str(database), 'verify')
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)['integrity'])
            self.assertEqual(database.read_bytes(), before)

    def test_wrappers_default_to_identical_canonical_identity(self):
        reference = json.loads(self.invoke('build-info').stdout)
        self.assertEqual(reference['code_hash'], code_hash())
        self.assertEqual(reference['model_hash'], model_code_hash())
        self.assertEqual(reference['policy_hash'], Policy().fingerprint)
        self.assertFalse(reference['monetary_permission'])
        for launcher in ('run_sefirot.py', 'SEFIROT_CORE.py'):
            result = self.invoke('build-info', launcher=launcher)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), reference)
            self.assertIn('DEPRECATED wrapper', result.stderr)

    def test_default_wrappers_do_not_import_legacy_or_grids(self):
        for launcher in ('sefirot.py', 'run_sefirot.py', 'SEFIROT_CORE.py'):
            program = """
import importlib.abc, runpy, sys
class BlockResearch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'sefirot_core' or fullname in (
                'sefirot.builder_research', 'sefirot.market_grid', 'sefirot.fixtures'):
            raise AssertionError('unexpected research import: ' + fullname)
sys.meta_path.insert(0, BlockResearch())
sys.argv = [sys.argv[1], 'build-info']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
            result = subprocess.run([sys.executable, '-c', program, str(ROOT/launcher)],
                                    cwd=ROOT, capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_interfaces_require_explicit_opt_in(self):
        for launcher in ('run_sefirot.py', 'SEFIROT_CORE.py'):
            result = self.invoke('--legacy', '--help', launcher=launcher)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('build-info', result.stdout)
            self.assertNotIn('--research-grids', result.stdout)
        result = self.invoke('analyze', launcher='run_sefirot.py')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Букмекер:', result.stdout)

    def test_legacy_help_handles_a_non_cyrillic_output_encoding(self):
        import os
        for launcher in ('run_sefirot.py', 'SEFIROT_CORE.py'):
            result = subprocess.run([sys.executable, str(ROOT/launcher), '--legacy', '--help'],
                                    cwd=ROOT, capture_output=True, encoding='utf-8',
                                    env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('usage:', result.stdout)

    def test_cli_research_grids_flag_is_explicit_and_does_not_grant_permissions(self):
        for explicit in (False, True):
            arguments = ['data-session', '--date', '2030-01-01', '--directory', 'unused',
                         '--league-profile', '9=LOWER', '--source-reliability', '.95']
            if explicit:
                arguments.append('--research-grids')
            with patch('sefirot.data_session.collect_session', return_value={'status': 'NO_USABLE_RESEARCH_FORECASTS'}) as collect, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
            self.assertIs(collect.call_args.kwargs['research_grids'], explicit)


if __name__ == '__main__':
    unittest.main()
