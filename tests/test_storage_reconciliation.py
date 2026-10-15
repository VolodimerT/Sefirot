"""Reconcile owned SQLite only; cloud observations are synthetic metadata."""
import copy
from contextlib import closing, redirect_stdout
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from scripts import storage_reconciliation as audit
from sefirot.contracts import time
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service


class StorageReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root/'original.sqlite'
        case = example()
        repo = Repository(self.path)
        try:
            self.prediction = Service(repo, clock=lambda: time(case['sports']['as_of'])).capture(
                case['sports'], case['markets'])
        finally:
            repo.close()
        self.before = self.path.read_bytes()
        packed = bytearray(gzip.compress(self.before, mtime=0)); packed[9] = 255
        checksum = hashlib.sha256(packed).hexdigest()
        self.observation = {'observed_at':'2030-01-01T10:00:00+00:00',
            'snapshot':{'revision':1,'checksum':checksum,'actual_compressed_sha256':checksum,
                        'updated_at':'2030-01-01T09:00:00+00:00'},
            'mirror_counts':{k:0 for k in audit.MIRROR_TABLES}}

    def test_canonical_match_explains_empty_mirror_without_writes_or_public_identity(self):
        with patch('sefirot.cloud_sync.mirror') as mirror:
            out, private = audit.reconcile(self.path, self.observation)
        mirror.assert_not_called()
        self.assertEqual(out['status'],'CANONICAL_CONTENT_MATCH')
        self.assertEqual(out['mirror_state'],'EMPTY_MATERIALIZED_LAYER')
        self.assertEqual(out['mirror_comparison'],'COUNTS_ONLY_NOT_CONTENT_VERIFIED')
        self.assertEqual(out['local_counts']['predictions'],1)
        self.assertEqual(private[0]['prediction_id'],self.prediction['id'])
        self.assertTrue(private[0]['ledger_witness_verified'])
        self.assertFalse(private[0]['provider_origin_independently_verified'])
        self.assertNotIn(self.prediction['id'],json.dumps(out))
        self.assertEqual(out['cloud_metadata_authority'],'CALLER_SUPPLIED_OBSERVATION')
        self.assertFalse(out['cloud_written']); self.assertFalse(out['original_written'])
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_repeated_review_is_deterministic_without_duplicate_predictions(self):
        first = audit.reconcile(self.path,self.observation)
        self.assertEqual(audit.reconcile(self.path,self.observation),first)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_different_snapshot_and_corrupt_remote_checksum_cannot_match(self):
        for actual in (self.observation['snapshot']['checksum'],'b'*64):
            obs=copy.deepcopy(self.observation);obs['snapshot']['checksum']='b'*64
            obs['snapshot']['actual_compressed_sha256']=actual
            out,_=audit.reconcile(self.path,obs)
            self.assertFalse(out['canonical_snapshot_matches'])
            self.assertEqual(out['status'],'CANONICAL_CONTENT_NOT_VERIFIED')

    def test_mirror_counts_do_not_prove_mirror_content(self):
        obs=copy.deepcopy(self.observation);obs['mirror_counts']['predictions']=1
        out,_=audit.reconcile(self.path,obs)
        self.assertEqual(out['mirror_state'],'CONTENT_RECONCILIATION_REQUIRED')
        self.assertEqual(out['mirror_comparison'],'COUNTS_ONLY_NOT_CONTENT_VERIFIED')

    def test_live_sidecars_are_rejected(self):
        for suffix in ('-wal','-shm','-journal'):
            side=Path(str(self.path)+suffix);side.touch()
            try:
                with self.assertRaisesRegex(ValueError,'OFFLINE_SNAPSHOT_REQUIRED'):
                    audit.reconcile(self.path,self.observation)
            finally:side.unlink()

    def test_corrupt_journal_is_not_relabelled_as_verified(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER audit_logs_no_update')
            db.execute("UPDATE audit_logs SET previous_hash=? WHERE id=1",('b'*64,))
        raw=self.path.read_bytes()
        with self.assertRaises(ValueError):audit.reconcile(self.path,self.observation)
        self.assertEqual(self.path.read_bytes(),raw)

    def test_cloud_metadata_rejects_missing_actual_hash_and_bad_counts(self):
        for mode in ('actual','negative','boolean','future','extra'):
            obs=copy.deepcopy(self.observation)
            if mode=='actual':obs['snapshot'].pop('actual_compressed_sha256')
            elif mode=='negative':obs['mirror_counts']['predictions']=-1
            elif mode=='boolean':obs['mirror_counts']['predictions']=True
            elif mode=='future':obs['snapshot']['updated_at']='2031-01-01T00:00:00Z'
            else:obs['secret']='SYNTHETIC_PRIVATE'
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):audit.reconcile(self.path,obs)

    def test_source_change_during_review_is_rejected(self):
        original=audit.snapshot
        def changed(owned):
            result=original(owned);self.path.write_bytes(self.before+b'changed');return result
        with patch.object(audit,'snapshot',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'SNAPSHOT_CHANGED_DURING_REVIEW'):
                audit.reconcile(self.path,self.observation)

    def test_private_inventory_is_exclusive_and_restricted(self):
        p=self.root/'private.json';audit._write_private(p,{'owned':'data'})
        if os.name!='nt':self.assertEqual(p.stat().st_mode & 0o777,0o600)
        with self.assertRaises(FileExistsError):audit._write_private(p,{})

    def test_cli_does_not_overwrite_input_and_sanitizes_invalid_sqlite(self):
        observation=self.root/'cloud.json';observation.write_text(json.dumps(self.observation))
        args=['--db',str(self.path),'--cloud-observation',str(observation),'--output',str(self.path)]
        with redirect_stdout(io.StringIO()):self.assertEqual(audit.main(args),2)
        self.assertEqual(self.path.read_bytes(),self.before)
        self.path.write_bytes(b'not sqlite')
        with redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(audit.main(args[:-1]+[str(self.root/'report.json')]),2)
        self.assertNotIn(str(self.path),captured.getvalue())


if __name__=='__main__':unittest.main()
