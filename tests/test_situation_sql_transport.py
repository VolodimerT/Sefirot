"""Real local HTTP -> authenticated relay -> PostgreSQL -> Python worker tests.

PGlite runs PostgreSQL 18 WASM; production Supabase is 17. This is an isolated
synthetic integration, not a deployed cloud check or authenticated sports feed.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import timedelta
import functools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts"),str(ROOT/"tests")]
from sefirot.contracts import canonical
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service
import chat_gateway
import chat_queue
import chat_situation
import chat_store
from test_situation_bridge import NOW, TEST_KEY, source, request

STORE_TOKEN="synthetic-store-token-for-local-tests-only-000000000000000000"


class SQLTransportTests(unittest.TestCase):
    def node(self):
        binary=shutil.which("node")
        self.assertIsNotNone(binary,"Node is required; never skip SQL verification")
        return binary

    def test_actual_sql_roles_idempotency_leases_and_gateway_errors(self):
        run=subprocess.run([self.node(),str(ROOT/"scripts/test_chat_situation.mjs")],
            cwd=ROOT,capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,0,run.stderr)
        result=json.loads(run.stdout)
        self.assertEqual(result["sql_groups"],14)
        self.assertEqual(result["gateway_groups"],11)
        self.assertEqual(result["source"],"SYNTHETIC_ONLY")

    def test_http_worker_receipt_durable_restart_and_original_seals(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory).resolve()
            process=subprocess.Popen([self.node(),str(ROOT/"scripts/test_chat_situation.mjs"),"--serve",str(root/"pg")],
                cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
            try:
                initial=json.loads(process.stdout.readline())
                self.assertTrue(initial["ready"])
                def control(data):
                    process.stdin.write(json.dumps(data)+"\n");process.stdin.flush()
                    text=process.stdout.readline()
                    self.assertTrue(text,"local PostgreSQL relay exited")
                    reply=json.loads(text)
                    self.assertNotIn("error",reply)
                    return reply.get("value",reply)
                stack.enter_context(patch.dict("os.environ",{
                    "SEFIROT_STORE_URL":"https://synthetic.test/functions/v1/sefirot-chat-store",
                    "SEFIROT_SITUATION_SOURCE_KEY":TEST_KEY,"SEFIROT_SITUATION_ALLOW_SYNTHETIC":"1"}))
                # Only this test allows loopback HTTP; real config keeps HTTPS.
                stack.enter_context(patch.object(chat_store,"config",return_value=(
                    f"http://127.0.0.1:{initial['port']}/functions/v1/sefirot-chat-store",STORE_TOKEN)))
                stack.enter_context(patch.object(chat_gateway,"execute_situation",
                    functools.partial(chat_situation.execute_situation,clock=lambda:NOW)))
                case=example(NOW,"synthetic-durable-status-only")
                path=root/"original.sqlite";repo=Repository(str(path)); current=[NOW]
                try:
                    service=Service(repo,clock=lambda:current[0])
                    prediction=service.capture(case["sports"],case["markets"])
                    current[0]=NOW+timedelta(minutes=2)
                    decision=service.decide(prediction["id"],case["quotes"],case["recheck"],
                        {"bankroll":1000.0,"peak":1000.0},case["decision_at"])
                    self.assertTrue(repo.verify())
                finally:repo.close()
                original=path.read_bytes()
                self.assertEqual(chat_store.checkpoint(path,0),1)
                calls_before=control({"command":"calls"})
                envelope=source();q=request(envelope)
                queued=control({"command":"enroll","request":q,"envelope":envelope})
                self.assertTrue(chat_queue.process_one())
                job=control({"command":"read","id":queued["job_id"]})
                self.assertEqual(job["status"],"DONE");self.assertEqual(job["attempts"],1)
                self.assertEqual(job["response"]["phase"],"PREMATCH")
                self.assertIs(job["response"]["monetary_permission"],False)
                new_calls=control({"command":"calls"})[len(calls_before):]
                self.assertEqual(new_calls,["sefirot_chat_claim","sefirot_situation_source","sefirot_situation_complete"])
                self.assertEqual(path.read_bytes(),original)
                self.assertTrue(control({"command":"restart"})["restarted"])
                reused=control({"command":"enqueue","request":q})
                self.assertTrue(reused["reused"]);self.assertEqual(reused["job_id"],queued["job_id"])
                self.assertFalse(chat_queue.process_one())
                restored=root/"restored.sqlite"
                self.assertEqual(chat_store.restore(restored),1)
                self.assertEqual(restored.read_bytes(),original)
                repo=Repository(str(restored),read_only=True)
                try:
                    self.assertTrue(repo.verify())
                    self.assertEqual(canonical(repo.get("predictions",prediction["id"])),canonical(prediction))
                    self.assertEqual(canonical(repo.get("decisions",decision["id"])),canonical(decision))
                    self.assertTrue(Service(repo).replay(decision["id"])["matches"])
                finally:repo.close()
                control({"command":"close"})
                process.wait(timeout=10)
                self.assertEqual(process.returncode,0,process.stderr.read())
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
                for stream in (process.stdin,process.stdout,process.stderr):stream.close()


if __name__=="__main__":unittest.main()
