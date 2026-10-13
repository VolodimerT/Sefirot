"""Owned loopback HTTP + original synthetic ledger; no real credentials/provider."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src"),str(ROOT/"scripts")]
from scripts.operator_cockpit import make_server,snapshot
from research.prematch_scenario import run_scenario
from sefirot.repository import Repository

TOKEN="SYNTHETIC_OPERATOR_TEST_ONLY_"+"x"*32

class PhoneOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.server=make_server(database=self.root/"missing.sqlite",token=TOKEN,at="2030-01-01T09:10:00+00:00")
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)

    def request(self,path="/api/operator",method="GET",body=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=30)
        try:
            conn.request(method,path,body=body,headers=headers or {})
            response=conn.getresponse();return response.status,dict(response.getheaders()),response.read()
        finally:conn.close()

    def test_no_data_401_and_authenticated_read_does_not_create_db(self):
        self.assertEqual(self.request()[0],401)
        status,headers,raw=self.request(headers={"Authorization":"Bearer "+TOKEN})
        self.assertEqual(status,200);data=json.loads(raw)["data"]
        self.assertEqual(data["ledger_status"],"ABSENT")
        self.assertEqual(data["verified_market_views"],[])
        self.assertFalse((self.root/"missing.sqlite").exists())
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertFalse(data["runtime_provenance"]["cloud_runtime_connected"])

    def test_login_cookie_is_http_only_and_wrong_origin_or_token_rejected(self):
        origin="http://127.0.0.1:"+str(self.server.server_port)
        hdr={"Origin":origin,"Content-Type":"application/json"}
        self.assertEqual(self.request("/session","POST",json.dumps({"token":"wrong"}),hdr)[0],401)
        self.assertEqual(self.request("/session","POST",json.dumps({"token":TOKEN}),
            {**hdr,"Origin":"https://untrusted.invalid"})[0],403)
        status,headers,raw=self.request("/session","POST",json.dumps({"token":TOKEN}),hdr)
        self.assertEqual(status,204);self.assertIn("HttpOnly",headers["Set-Cookie"])
        self.assertIn("SameSite=Strict",headers["Set-Cookie"])
        cookie=headers["Set-Cookie"].split(";")[0]
        self.assertEqual(self.request(headers={"Cookie":cookie})[0],200)
        self.assertNotIn(TOKEN,headers["Set-Cookie"])

    def test_expired_session_and_write_live_paid_policy_paths_refuse(self):
        with self.server.session_lock:self.server.sessions["synthetic-expired"]=0
        self.assertEqual(self.request(headers={"Cookie":"sefirot_operator=synthetic-expired"})[0],401)
        auth={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"}
        for path in ("/v1/capture","/v1/decide","/v1/result","/run","/policy","/paid-fetch","/LIVE"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path,"POST","{}",auth)[0],403)
                self.assertEqual(self.request(path,headers=auth)[0],403)
        for method in ("PUT","PATCH","DELETE"):
            self.assertEqual(self.request("/session",method,"{}",auth)[0],403)
        self.assertEqual(self.request("/api/operator?mode=LIVE",headers=auth)[0],403)
        self.assertFalse((self.root/"missing.sqlite").exists())

    def test_static_assets_contain_no_token_private_data_or_write_controls(self):
        for path in ("/","/operator.css","/operator.mjs"):
            status,headers,raw=self.request(path)
            self.assertEqual(status,200);self.assertNotIn(TOKEN.encode(),raw)
            self.assertEqual(headers["Cache-Control"],"no-store")
        html=self.request("/")[2].decode()
        self.assertIn('name="viewport"',html)
        self.assertNotIn("Обработать очередь",html)
        self.assertNotIn("Сделать ставку",html)

    def test_original_pass_market_views_are_readonly_not_fresh_quote_permission(self):
        work=self.root/"work";scenario=run_scenario(work_directory=work)
        db=work/"scenario.sqlite";before=db.read_bytes()
        out=snapshot(db,at="2030-01-01T09:10:00+00:00")
        self.assertEqual(db.read_bytes(),before)
        record=out["verified_market_views"][0]
        self.assertEqual(record["core_decision"],"PASS")
        self.assertEqual(record["core_class"],"D")
        self.assertFalse(record["fresh_quote_attested"])
        self.assertEqual(record["source"],"ORIGINAL_VERIFIED_DECISION_CARD")
        self.assertIsNotNone(record["markets"][0]["model_probability"])
        self.assertIsNotNone(record["markets"][0]["ev"])
        self.assertFalse(out["monetary_permission"])

    def test_stale_quote_is_a_saved_blocker_not_new_price(self):
        work=self.root/"work";run_scenario(work_directory=work)
        db=work/"scenario.sqlite"
        out=snapshot(db,at="2030-01-01T10:00:00+00:00")
        self.assertFalse(out["verified_market_views"][0]["fresh_quote_attested"])
        self.assertEqual(out["verified_market_views"][0]["core_decision"],"PASS")

    def test_changed_current_build_preserves_original_hash_and_pass(self):
        work=self.root/"work";run_scenario(work_directory=work)
        with patch("research.prematch_readiness.code_hash",return_value="f"*64), \
             patch("sefirot.readiness.code_hash",return_value="f"*64):
            out=snapshot(work/"scenario.sqlite",at="2030-01-01T09:02:00+00:00")
        record=out["verified_market_views"][0]
        self.assertFalse(record["build_matches"])
        self.assertNotEqual(record["code_hash"],out["build"]["code_hash"])
        self.assertEqual(record["core_decision"],"PASS")
        self.assertEqual(out["readiness"][0]["status"],"BUILD_MISMATCH")

    @unittest.skipUnless(shutil.which("node"),"Node required for original frontend smoke")
    def test_actual_frontend_no_data_source_blocked_filters_and_pass_invariants(self):
        result=subprocess.run(["node",str(ROOT/"scripts/test_operator_cockpit.mjs")],
            cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("OPERATOR_FRONTEND_CASES=8",result.stdout)
