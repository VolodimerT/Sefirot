"""Historical replay must route to matching code without modifying old seals."""
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import os

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

    def test_git_replace_and_inherited_git_object_override_cannot_change_pinned_build(self):
        source = self.repo/'src'/'sefirot'/'odds_provider.py'
        source.write_text(source.read_text()+'\n# replacement object\n')
        subprocess.run(['git','-C',str(self.repo),'add','src/sefirot'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=QA',
                        '-c','user.email=qa@example.invalid','commit','-qm','replacement'],
                       check=True,capture_output=True)
        replacement = subprocess.check_output(['git','-C',str(self.repo),'rev-parse','HEAD'],
                                              text=True).strip()
        subprocess.run(['git','-C',str(self.repo),'replace',self.commit,replacement],
                       check=True,capture_output=True)
        with patch.dict(os.environ,{'GIT_OBJECT_DIRECTORY':str(self.root/'invalid-object-store')}):
            result = replay_historical(self.ledger,self.case['decision_id'],
                                       builds={'REVIEWED':self.commit},repo_root=self.repo)
        self.assertEqual(result['status'],'MATCH')
        self.assertEqual(result['commit'],self.commit)
        self.assertEqual(sha256(self.ledger.read_bytes()).hexdigest(),self.before)

    def test_nested_executable_package_outside_code_hash_is_rejected(self):
        nested=self.repo/'src'/'sefirot'/'unhashed_plugin'
        nested.mkdir()
        (nested/'__init__.py').write_text('raise RuntimeError("must not execute")\n')
        subprocess.run(['git','-C',str(self.repo),'add','src/sefirot'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=QA',
                        '-c','user.email=qa@example.invalid','commit','-qm','nested package'],
                       check=True,capture_output=True)
        nested_commit=subprocess.check_output(['git','-C',str(self.repo),'rev-parse','HEAD'],
                                              text=True).strip()
        with self.assertRaisesRegex(ValueError,'INVALID_BUILD_ARCHIVE'):
            replay_historical(self.ledger,self.case['decision_id'],
                              builds={'NESTED':nested_commit},repo_root=self.repo)

    def test_corrupted_git_blob_cannot_be_used_as_archived_code(self):
        object_id=subprocess.check_output(['git','-C',str(self.repo),'rev-parse',
            self.commit+':src/sefirot/identity.py'],text=True).strip()
        blob=self.repo/'.git'/'objects'/object_id[:2]/object_id[2:]
        self.assertTrue(blob.is_file())
        data=blob.read_bytes()
        blob.chmod(0o600)
        blob.write_bytes(data[:8]+bytes([data[8]^1])+data[9:])
        with self.assertRaisesRegex(ValueError,'PINNED_BUILD_UNAVAILABLE|GIT_OBJECT_HASH_MISMATCH'):
            replay_historical(self.ledger,self.case['decision_id'],
                              builds={'REVIEWED':self.commit},repo_root=self.repo)
        self.assertEqual(sha256(self.ledger.read_bytes()).hexdigest(),self.before)
