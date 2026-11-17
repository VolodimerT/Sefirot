"""Historical replay must route to matching code without modifying old seals."""
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from research.historical_replay import replay_historical
from research.prematch_scenario import run_scenario

ROOT = Path(__file__).resolve().parents[1]


class HistoricalReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root/'reviewed-build'
        shutil.copytree(ROOT/'src'/'sefirot', self.repo/'src'/'sefirot',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), 'add', 'src/sefirot'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=QA',
                        '-c', 'user.email=qa@example.invalid', 'commit', '-qm', 'reviewed build'],
                       check=True, capture_output=True)
        self.commit = subprocess.check_output(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'],
                                              text=True).strip()
        self.case = run_scenario(work_directory=self.root/'case')
        self.ledger = self.root/'case'/'scenario.sqlite'
        self.before = sha256(self.ledger.read_bytes()).hexdigest()

    def test_exact_archived_build_replays_copy_without_ledger_mutation(self):
        result = replay_historical(self.ledger, self.case['decision_id'],
                                   builds={'REVIEWED': self.commit}, repo_root=self.repo)
        self.assertEqual(result['status'], 'MATCH')
        self.assertEqual(result['build'], 'REVIEWED')
        self.assertEqual(result['code_hash'], self.case['build']['code_hash'])
        self.assertTrue(result['original_unchanged'] and result['copy_unchanged'])
        self.assertEqual(sha256(self.ledger.read_bytes()).hexdigest(), self.before)

    def test_wrong_build_and_uncheckpointed_ledger_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_HISTORICAL_BUILD'):
            replay_historical(self.ledger, self.case['decision_id'], builds={}, repo_root=self.repo)
        wal = Path(str(self.ledger)+'-wal')
        wal.write_bytes(b'uncheckpointed')
        with self.assertRaisesRegex(ValueError, 'CHECKPOINTED_REGULAR_LEDGER_REQUIRED'):
            replay_historical(self.ledger, self.case['decision_id'],
                              builds={'REVIEWED': self.commit}, repo_root=self.repo)
        self.assertEqual(sha256(self.ledger.read_bytes()).hexdigest(), self.before)

    def test_unknown_decision_and_invalid_build_label_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'DECISION_NOT_FOUND'):
            replay_historical(self.ledger, 'a'*64,
                              builds={'REVIEWED': self.commit}, repo_root=self.repo)
        with self.assertRaisesRegex(ValueError, 'INVALID_BUILD_LABEL'):
            replay_historical(self.ledger, self.case['decision_id'],
                              builds={'../untrusted': self.commit}, repo_root=self.repo)
