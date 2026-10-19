"""Archive continuation and actual CLI failures; isolated owned data only."""
from pathlib import Path
from contextlib import redirect_stdout
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from sefirot.contracts import canonical
from sefirot.repository import Repository
from research import football_pipeline as pipe
from test_football_pipeline import packet


class FootballSyncRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'sources.sqlite'
        self.repo=Repository(self.path);self.addCleanup(self.repo.close)

    def rows(self):
        rows=[]
        for n in range(3):
            raw=canonical(packet(at=f'2026-10-16T12:0{n}:00+00:00'))
            key=pipe.sha256(raw.encode()).hexdigest()
            rows.append({'raw_source':raw,'raw_sha256':key,'next':key})
        return sorted(rows,key=lambda r:r['next'])

    def relay(self,rows,calls):
        def request(query):
            calls.append(query)
            return next((r for r in rows if r['next']>query['after']),{'next':None})
        return request

    def test_bounded_pages_can_reach_packets_beyond_first_page(self):
        rows=self.rows();calls=[];request=self.relay(rows,calls)
        with patch('scripts.chat_sports_probe.get_sports') as provider:
            first=pipe.sync_archive(self.repo,request=request,limit=1)
            self.assertFalse(first['complete'])
            self.assertEqual(first.get('next_after'),rows[0]['next'])
            second=pipe.sync_archive(self.repo,request=request,limit=1,after=first['next_after'])
            third=pipe.sync_archive(self.repo,request=request,limit=2,after=second['next_after'])
            provider.assert_not_called()
        self.assertTrue(third['complete'])
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),3)
        self.assertEqual(third['next_after'],'')
        self.assertTrue(self.repo.verify())

    def test_completed_cycle_rescans_new_lower_hash_and_keeps_first_availability(self):
        rows=self.rows();calls=[]
        first=pipe.sync_archive(self.repo,request=self.relay(rows[1:],calls))
        self.assertTrue(first['complete'])
        old={r['id']:r['at'] for r in pipe._records(self.repo,pipe.SOURCE)}
        second=pipe.sync_archive(self.repo,request=self.relay(rows,calls),after=first.get('next_after'))
        self.assertEqual(second['added_sources'],1)
        self.assertTrue(all(r['at']==old[r['id']] for r in pipe._records(self.repo,pipe.SOURCE) if r['id'] in old))

    def test_crash_after_page_preserves_committed_source_and_replay_is_idempotent(self):
        rows=self.rows();calls=[]
        request=self.relay(rows,calls)
        def fail(query):
            if calls:raise OSError('SYNTHETIC_RELAY_DISCONNECT')
            return request(query)
        with self.assertRaises(OSError):pipe.sync_archive(self.repo,request=fail)
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),1)
        recovered=pipe.sync_archive(self.repo,request=request)
        self.assertEqual(recovered['added_sources'],2)
        self.assertTrue(recovered['complete']);self.assertTrue(self.repo.verify())

    def test_invalid_cursor_refuses_before_relay_or_source_writes(self):
        for cursor in (None,1,'A'*64,'f'*63,'secret/SYNTHETIC'):
            with self.subTest(cursor=cursor),patch('scripts.chat_store.request') as relay:
                with self.assertRaisesRegex(ValueError,'SOURCE_EXPORT_CURSOR_INVALID'):
                    pipe.sync_archive(self.repo,after=cursor)
                relay.assert_not_called()
        self.assertEqual(pipe._records(self.repo,pipe.SOURCE),[])

    def test_cursor_from_another_database_cannot_skip_unimported_sources(self):
        with patch('scripts.chat_store.request') as relay:
            with self.assertRaisesRegex(ValueError,'SOURCE_EXPORT_CURSOR_NOT_IMPORTED'):
                pipe.sync_archive(self.repo,after='a'*64)
            relay.assert_not_called()

    def test_corrupt_source_cli_fails_safely_without_modifying_bytes(self):
        corrupt=Path(self.temp.name)/'corrupt.sqlite';original=b'OWNED_NOT_A_SQLITE_DATABASE'
        corrupt.write_bytes(original);out=Path(self.temp.name)/'output.json'
        result=subprocess.run([sys.executable,str(ROOT/'scripts/football_pipeline.py'),
            '--source-db',str(corrupt),'--output',str(out),'coverage'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(result.stderr.strip(),'PIPELINE_STOPPED: SOURCE_STORAGE_OR_VALIDATION_GATE')
        self.assertNotIn('Traceback',result.stderr);self.assertFalse(out.exists())
        self.assertEqual(corrupt.read_bytes(),original)

    def test_cli_passes_continuation_and_writes_private_report(self):
        from scripts import football_pipeline as cli
        rows=self.rows();calls=[];output=Path(self.temp.name)/'sync.json'
        with patch('scripts.chat_store.request',side_effect=self.relay(rows,calls)),redirect_stdout(io.StringIO()):
            code=cli.main(['--source-db',str(self.path),'--output',str(output),
                           'sync-archive','--limit','1'])
        self.assertEqual(code,0);report=json.loads(output.read_text())
        self.assertEqual(report['next_after'],rows[0]['next'])
        output2=Path(self.temp.name)/'sync2.json'
        with patch('scripts.chat_store.request',side_effect=self.relay(rows,calls)),redirect_stdout(io.StringIO()):
            code=cli.main(['--source-db',str(self.path),'--output',str(output2),
                           'sync-archive','--limit','3','--after',report['next_after']])
        self.assertEqual(code,0);self.assertTrue(json.loads(output2.read_text())['complete'])
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),3)
        if sys.platform!='win32':self.assertEqual(output.stat().st_mode & 0o777,0o600)


if __name__=='__main__':unittest.main()
