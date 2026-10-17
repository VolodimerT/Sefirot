"""Durable SEFIROT checkpoint tests: CAS, integrity and fail-closed behavior."""
import base64
from email.message import Message
import io
import json
from contextlib import contextmanager
import gzip
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPSHandler, build_opener
from urllib.response import addinfourl
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import chat_store
from sefirot.repository import Repository

class DurableStoreTests(unittest.TestCase):
    def test_live_wal_checkpoint_is_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"synthetic.sqlite"
            repo=Repository(str(path))
            try:
                repo.db.execute('PRAGMA journal_mode=WAL')
                payload={'id':'synthetic-job','at':'2030-01-01T00:00:00+00:00'}
                with repo.transaction():
                    repo.insert('jobs',payload['id'],payload,at=payload['at'])
                    repo.record_log('jobs',payload['id'],payload['at'],payload)
                before=path.read_bytes()
                with patch.object(chat_store,'request') as transport:
                    with self.assertRaisesRegex(RuntimeError,'REQUIRES_OFFLINE_SNAPSHOT'):
                        chat_store.checkpoint(path,0)
                transport.assert_not_called()
                self.assertEqual(path.read_bytes(),before)
            finally:repo.close()

    def test_header_and_checksum_do_not_make_corrupt_restore_valid(self):
        packed=gzip.compress(b'SQLite format 3\x00'+b'\x00'*4096,mtime=0)
        record={'revision':1,'snapshot':base64.b64encode(packed).decode(),
                'checksum':hashlib.sha256(packed).hexdigest()}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'not-created'/'synthetic.sqlite'
            with patch.object(chat_store,'request',return_value=record):
                with self.assertRaisesRegex(RuntimeError,'STORE_SNAPSHOT_INTEGRITY_FAILED'):
                    chat_store.restore(path)
            self.assertFalse(path.parent.exists())

    def test_invalid_journal_checkpoint_is_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.sqlite';path.write_bytes(b'SQLite format 3\x00'+b'\x00'*4096)
            before=path.read_bytes()
            with patch.object(chat_store,'request') as transport:
                with self.assertRaisesRegex(RuntimeError,'SQLITE_CHECKPOINT_INTEGRITY_FAILED'):
                    chat_store.checkpoint(path,0)
            transport.assert_not_called();self.assertEqual(path.read_bytes(),before)

    def test_checkpoint_source_change_during_verification_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.sqlite';repo=Repository(str(path));repo.close()
            verify=chat_store._verify_snapshot_bytes
            def concurrent(raw):
                verify(raw);path.write_bytes(raw+b'changed')
            with patch.object(chat_store,'_verify_snapshot_bytes',side_effect=concurrent),patch.object(chat_store,'request') as transport:
                with self.assertRaisesRegex(RuntimeError,'SQLITE_CHECKPOINT_CHANGED_DURING_READ'):
                    chat_store.checkpoint(path,0)
            transport.assert_not_called()

    def test_roundtrip_preserves_original_verified_sqlite(self):
        state={"revision":0,"snapshot":None,"checksum":None}
        def fake_request(message):
            if message["action"]=="pull": return dict(state)
            if message["revision"]!=state["revision"]:raise RuntimeError("STALE")
            data=base64.b64decode(message["snapshot"],validate=True)
            if hashlib.sha256(data).hexdigest()!=message["checksum"]:raise RuntimeError("BAD_HASH")
            state.update(revision=state["revision"]+1,snapshot=message["snapshot"],checksum=message["checksum"])
            return {"revision":state["revision"],"checksum":message["checksum"]}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"one.sqlite"
            repo=Repository(str(path))
            self.assertTrue(repo.verify());repo.close()
            with patch.object(chat_store,"request",side_effect=fake_request):
                self.assertEqual(chat_store.checkpoint(path,0),1)
                restored=Path(temp)/"two.sqlite"
                self.assertEqual(chat_store.restore(restored),1)
                second=Repository(str(restored),read_only=True)
                try:self.assertTrue(second.verify())
                finally:second.close()
                with self.assertRaisesRegex(RuntimeError,"STALE"):
                    chat_store.checkpoint(path,0)

    def test_reject_corrupted_checkpoint(self):
        packed=gzip.compress(b"this is NOT SQLite",mtime=0)
        record={"revision":1,"snapshot":base64.b64encode(packed).decode(),
                "checksum":hashlib.sha256(packed).hexdigest()}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(chat_store,"request",return_value=record):
                with self.assertRaisesRegex(RuntimeError,"INTEGRITY"):
                    chat_store.restore(Path(temp)/"bad.sqlite")

    def test_fail_closed_without_token(self):
        with patch.dict("os.environ",{"SEFIROT_STORE_URL":"https://example.supabase.co/functions/v1/sefirot-chat-store",
                                      "SEFIROT_STORE_TOKEN":""}):
            with self.assertRaisesRegex(RuntimeError,"token unavailable"):
                chat_store.config()

    def transport(self, status=200, location=None, raw=b'{"ok":true,"data":{"revision":0}}'):
        owner = self
        self.calls = []
        self.replies = []
        class MemoryTransport(HTTPSHandler, HTTPHandler):
            def https_open(self, request):
                owner.calls.append(request)
                headers = Message()
                if location: headers['Location'] = location
                reply = addinfourl(io.BytesIO(raw), headers, request.full_url, status)
                reply.msg = 'test response'
                owner.replies.append(reply)
                return reply
            http_open = https_open
        real_builder = build_opener
        return lambda *handlers: real_builder(*handlers, MemoryTransport())

    def test_private_header_never_reaches_any_redirect_destination(self):
        for code in (301, 302, 303, 307, 308):
            for location in ('https://other.example.test/collect', 'http://other.example.test/collect'):
                with self.subTest(code=code, location=location), \
                     patch.dict('os.environ', {'SEFIROT_STORE_URL': 'https://store.example.test/functions/v1/sefirot-chat-store',
                                              'SEFIROT_STORE_TOKEN': 'SYNTHETIC_TEST_ONLY_' * 3}), \
                     patch.object(chat_store, 'build_opener', side_effect=self.transport(code, location)):
                    with self.assertRaisesRegex(RuntimeError, '^SEFIROT_DURABLE_STORE_UNAVAILABLE$'):
                        chat_store.request({'action': 'pull'})
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(urlsplit(self.calls[0].full_url).hostname, 'store.example.test')
                self.assertTrue(self.replies[0].closed)

    def test_valid_store_http_roundtrip_uses_configured_endpoint(self):
        with patch.dict('os.environ', {'SEFIROT_STORE_URL': 'https://store.example.test/functions/v1/sefirot-chat-store',
                                     'SEFIROT_STORE_TOKEN': 'SYNTHETIC_TEST_ONLY_' * 3}), \
             patch.object(chat_store, 'build_opener', side_effect=self.transport()):
            self.assertEqual(chat_store.request({'action': 'pull'}), {'revision': 0})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0].get_method(), 'POST')
        self.assertEqual(json.loads(self.calls[0].data), {'action': 'pull'})
        self.assertTrue(self.replies[0].closed)

    def test_malformed_store_urls_fail_before_transport(self):
        for url in ('http://store.example.test/functions/v1/sefirot-chat-store',
                    'https:///functions/v1/sefirot-chat-store',
                    'https://user:password@store.example.test/functions/v1/sefirot-chat-store',
                    'https://store.example.test:bad/functions/v1/sefirot-chat-store',
                    'https://store.example.test/other?next=/functions/v1/sefirot-chat-store',
                    'https://store.example.test/functions/v1/sefirot-chat-store#fragment'):
            with self.subTest(url=url), patch.dict('os.environ', {'SEFIROT_STORE_URL': url,
                        'SEFIROT_STORE_TOKEN': 'SYNTHETIC_TEST_ONLY_' * 3}), \
                 patch.object(chat_store, 'build_opener') as transport:
                with self.assertRaisesRegex(RuntimeError, 'URL unavailable'): chat_store.request({'action': 'pull'})
                transport.assert_not_called()

    def test_invalid_response_shape_is_a_fixed_public_error(self):
        for raw in (b'[]', b'null', b'1', b'{"ok":true,"data":[]}', b'{'):
            with self.subTest(raw=raw), patch.dict('os.environ', {
                    'SEFIROT_STORE_URL': 'https://store.example.test/functions/v1/sefirot-chat-store',
                    'SEFIROT_STORE_TOKEN': 'SYNTHETIC_TEST_ONLY_' * 3}), \
                 patch.object(chat_store, 'build_opener', side_effect=self.transport(raw=raw)):
                with self.assertRaisesRegex(RuntimeError, '^SEFIROT_DURABLE_STORE_INVALID_RESPONSE$'):
                    chat_store.request({'action': 'pull'})

if __name__=="__main__":
    unittest.main()
