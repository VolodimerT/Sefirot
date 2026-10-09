"""Durable SEFIROT checkpoint tests: CAS, integrity and fail-closed behavior."""
import base64
from contextlib import contextmanager
import gzip
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import chat_store
from sefirot.repository import Repository

class DurableStoreTests(unittest.TestCase):
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

if __name__=="__main__":
    unittest.main()
