"""Adversarial status-only integration. Every source in this file is synthetic."""
from __future__ import annotations

import base64
from contextlib import ExitStack
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import functools
import hashlib
import hmac
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT)]
from sefirot.contracts import canonical, digest
from sefirot.engine import model_code_hash
from sefirot.repository import Repository
from research.situation_contract import SituationRequest, SituationResponse
from research.situational_v1 import route_fixture, screen_alternatives
import chat_gateway
import chat_mcp
import chat_queue
import chat_situation
import chat_store

NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
TEST_KEY = "synthetic-fixture-key-for-local-tests-only-000000000000"
TEST_TOKEN = "synthetic-bridge-bearer-for-local-tests-only-0000000"


def source(status="NS", *, kickoff=None, observed=None, received=None, origin="SYNTHETIC_TEST_ONLY", revision=1):
    body = {"schema": "situation-source-receipt-v1", "fixture_id": "synthetic:fixture:123",
            "source_id": "synthetic-source", "source_revision": revision, "provider_status": status,
            "kickoff": (kickoff or NOW+timedelta(hours=2)).isoformat(),
            "status_observed_at": (observed or NOW-timedelta(seconds=2)).isoformat(),
            "status_received_at": (received or NOW-timedelta(seconds=1)).isoformat(), "origin": origin}
    envelope = {"body": body, "collector_signature": hmac.new(TEST_KEY.encode(), canonical(body).encode(), hashlib.sha256).hexdigest()}
    return envelope


def request(envelope, *, at=NOW, intent="auto", depth="auto"):
    b = envelope["body"]
    key = digest(b)
    return {"fixture_id": b["fixture_id"], "provider_status": b["provider_status"], "kickoff": b["kickoff"],
            "status_observed_at": b["status_observed_at"], "request_at": at.isoformat(), "intent": intent,
            "depth": depth, "original_provider_receipt_id": key,
            "identity": {"source_id": b["source_id"], "source_revision": b["source_revision"],
                         "receipt_hash": key, "model_hash": model_code_hash()}}


class SituationHarness(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.receipts = self.folder / "receipts"
        self.receipts.mkdir()
        self.stack.enter_context(patch.dict("os.environ", {
            "SEFIROT_STORE_URL": "", "SEFIROT_SITUATION_RECEIPTS": str(self.receipts),
            "SEFIROT_SITUATION_SOURCE_KEY": TEST_KEY, "SEFIROT_SITUATION_ALLOW_SYNTHETIC": "1",
            "SEFIROT_BRIDGE_TOKEN": TEST_TOKEN, "SEFIROT_BRIDGE_DB": str(self.folder / "canonical.sqlite")}))
        self.addCleanup(self.stack.close)

    def enroll(self, envelope):
        p = self.receipts / (digest(envelope["body"]) + ".json")
        p.write_text(json.dumps(envelope, allow_nan=False), encoding="utf-8")
        return request(envelope)

    def run_case(self, status="NS", *, at=NOW, intent="auto", depth="auto", **kwargs):
        envelope = source(status, **kwargs)
        q = self.enroll(envelope)
        q.update(request_at=at.isoformat(), intent=intent, depth=depth)
        return chat_situation.execute_situation(q, clock=lambda: at)

    def assert_closed(self, out):
        for key in ("monetary_permission", "execution_enabled", "prematch_core_allowed",
                    "core_invoked", "live_betting_allowed", "external_origin_verified"):
            self.assertIs(out[key], False, key)
        self.assertNotIn("probability", out)
        self.assertNotIn("ev", out)
        self.assertNotIn("alternatives", out)
        self.assertEqual(len(out["reasons"]), 1)
        self.assertIsInstance(out["next_action"], str)
        self.assertGreaterEqual(out["measured_processing_ms"], 0)


class SituationTests(SituationHarness):
    def test_deep_synthetic_prematch_and_typed_output(self):
        out = self.run_case()
        self.assertEqual((out["phase"], out["depth"]), ("PREMATCH", "DEEP"))
        self.assertTrue(out["synthetic"])
        self.assertTrue(out["collector_authenticated"])
        self.assertEqual(out["source_attestation"], "SYNTHETIC_TEST_ONLY")
        self.assertEqual(set(out), set(SituationResponse.__dataclass_fields__))
        self.assert_closed(out)

    def test_near_kickoff_forces_fast(self):
        out = self.run_case(kickoff=NOW+timedelta(minutes=4), depth="deep")
        self.assertEqual((out["phase"], out["depth"]), ("PREMATCH", "FAST"))
        self.assert_closed(out)

    def test_kickoff_minus_one_exact_and_plus_one(self):
        for seconds, expected in ((-1, "PREMATCH"), (0, "HOLD"), (1, "HOLD")):
            with self.subTest(seconds=seconds):
                self.assertEqual(self.run_case(kickoff=NOW, at=NOW+timedelta(seconds=seconds))["phase"], expected)

    def test_statuses_live_and_halftime(self):
        for status in ("1H", "HT", "2H", "ET", "LIVE"):
            with self.subTest(status=status):
                out = self.run_case(status, kickoff=NOW-timedelta(minutes=50))
                self.assertEqual((out["phase"], out["depth"]), ("LIVE_RESEARCH", "FAST"))
                self.assert_closed(out)

    def test_finished_status_has_no_forecast_or_settlement_write(self):
        for status in ("FT", "AET", "PEN"):
            with self.subTest(status=status):
                out = self.run_case(status, kickoff=NOW-timedelta(hours=2))
                self.assertEqual(out["phase"], "POSTMATCH")
                self.assert_closed(out)

    def test_regulation_ft_requires_90_minutes_at_original_observation(self):
        for elapsed, phase in ((1, "HOLD"), (5399, "HOLD"), (5400, "POSTMATCH")):
            with self.subTest(elapsed=elapsed):
                out = self.run_case("FT", kickoff=NOW-timedelta(seconds=elapsed),
                                    observed=NOW, received=NOW)
                self.assertEqual(out["phase"], phase)
                if phase == "HOLD":
                    self.assertEqual(out["reasons"], ["FINISHED_STATUS_CHRONOLOGY_CONFLICT"])
                self.assert_closed(out)

    def test_ft_age_uses_original_observation_not_newer_receipt(self):
        out = self.run_case("FT", kickoff=NOW-timedelta(minutes=90),
                            observed=NOW-timedelta(seconds=1), received=NOW)
        self.assertEqual(out["phase"], "HOLD")
        self.assertEqual(out["reasons"], ["FINISHED_STATUS_CHRONOLOGY_CONFLICT"])
        self.assert_closed(out)

    def test_stopped_unknown_and_no_automatic_live(self):
        for status in ("PST", "CANC", "SUSP", "ABD", "TBD", "UNKNOWN", "NS"):
            with self.subTest(status=status):
                self.assertEqual(self.run_case(status, kickoff=NOW-timedelta(minutes=2))["phase"], "HOLD")

    def test_delayed_observation_is_not_refreshed_by_new_receipt(self):
        out = self.run_case("1H", kickoff=NOW-timedelta(minutes=10), observed=NOW-timedelta(seconds=31))
        self.assertEqual(out["reasons"], ["STALE_LIVE_STATUS"])

    def test_live_30_seconds_boundary(self):
        self.assertEqual(self.run_case("1H", kickoff=NOW-timedelta(minutes=10), observed=NOW-timedelta(seconds=30))["phase"], "LIVE_RESEARCH")

    def test_ns_freshness_boundaries(self):
        for age, minutes, phase in ((120,4,"PREMATCH"),(121,4,"HOLD"),(900,60,"PREMATCH"),(901,60,"HOLD")):
            with self.subTest(age=age,minutes=minutes):
                self.assertEqual(self.run_case(observed=NOW-timedelta(seconds=age), kickoff=NOW+timedelta(minutes=minutes))["phase"], phase)

    def test_intent_conflicts(self):
        self.assertEqual(self.run_case(intent="live")["phase"], "HOLD")
        self.assertEqual(self.run_case("2H", kickoff=NOW-timedelta(minutes=60), intent="prematch")["phase"], "HOLD")

    def test_live_observed_before_kickoff_rejected_even_if_received_later(self):
        self.assertEqual(self.run_case("1H", kickoff=NOW-timedelta(seconds=1), observed=NOW-timedelta(seconds=2))["reasons"], ["INPLAY_STATUS_CHRONOLOGY_CONFLICT"])

    def test_future_and_impossible_receipt(self):
        for observed, received in ((NOW+timedelta(seconds=1), NOW+timedelta(seconds=2)), (NOW, NOW-timedelta(seconds=1))):
            with self.subTest(observed=observed):
                self.assertEqual(self.run_case(observed=observed,received=received)["reasons"], ["SOURCE_POINT_IN_TIME_CONFLICT"])

    def test_request_time_cannot_replay_old_status_as_current(self):
        q = self.enroll(source())
        for at, reason in ((NOW+timedelta(seconds=1),"FUTURE_REQUEST_TIME"),(NOW-timedelta(seconds=121),"REQUEST_EXPIRED")):
            q["request_at"] = at.isoformat()
            self.assertEqual(chat_situation.execute_situation(q, clock=lambda: NOW)["reasons"], [reason])

    def test_source_not_available_at_original_request(self):
        q = self.enroll(source(observed=NOW-timedelta(seconds=10)))
        q["request_at"] = (NOW-timedelta(seconds=5)).isoformat()
        self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"], ["SOURCE_POINT_IN_TIME_CONFLICT"])

    def test_real_archive_hmac_is_not_provider_attestation(self):
        out = self.run_case(origin="UNATTESTED_ARCHIVE")
        self.assertEqual(out["phase"], "HOLD")
        self.assertEqual(out["reasons"], ["SOURCE_ORIGIN_NOT_ATTESTED"])
        self.assertTrue(out["collector_authenticated"])
        self.assertFalse(out["synthetic"])
        self.assert_closed(out)

    def test_forged_external_origin_cannot_enable_source(self):
        out = self.run_case(origin="VERIFIED")
        self.assertEqual(out["phase"], "HOLD")
        self.assert_closed(out)

    def test_synthetic_needs_operator_opt_in(self):
        with patch.dict("os.environ", {"SEFIROT_SITUATION_ALLOW_SYNTHETIC":"0"}):
            self.assertEqual(self.run_case()["reasons"], ["SYNTHETIC_SOURCE_DISABLED"])

    def test_current_model_identity_required(self):
        q = self.enroll(source()); q["identity"]["model_hash"] = "0"*64
        with patch.object(chat_situation,"resolve_source") as lookup:
            self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"], ["MODEL_IDENTITY_MISMATCH"])
            lookup.assert_not_called()

    def test_foreign_fixture_status_kickoff_revision_and_source(self):
        q = self.enroll(source())
        changes = [("fixture_id","synthetic:fixture:456"),("provider_status","1H"),
                   ("kickoff",(NOW+timedelta(hours=1)).isoformat()),
                   ("status_observed_at",(NOW-timedelta(seconds=3)).isoformat())]
        for field, value in changes:
            with self.subTest(field=field):
                obj = {**q, field:value}
                self.assertEqual(chat_situation.execute_situation(obj,clock=lambda: NOW)["reasons"], ["SOURCE_ASSERTION_MISMATCH"])
        for field,value in (("source_revision",2),("source_id","foreign-source")):
            obj = {**q,"identity":{**q["identity"],field:value}}
            self.assertEqual(chat_situation.execute_situation(obj,clock=lambda: NOW)["reasons"], ["SOURCE_ASSERTION_MISMATCH"])

    def test_original_receipt_hash_and_hmac_tampering(self):
        obj = source(); q = self.enroll(obj); p = self.receipts/(q["original_provider_receipt_id"]+".json")
        obj["collector_signature"] = "0"*64; p.write_text(json.dumps(obj))
        self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"], ["SOURCE_COLLECTOR_AUTH_FAILED"])
        obj["body"]["kickoff"] = NOW.isoformat(); p.write_text(json.dumps(obj))
        self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"], ["SOURCE_RECEIPT_HASH_MISMATCH"])

    def test_missing_auth_and_source_record(self):
        q = self.enroll(source())
        with patch.dict("os.environ", {"SEFIROT_SITUATION_SOURCE_KEY":""}):
            self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"], ["SOURCE_AUTH_NOT_CONFIGURED"])
        (self.receipts/(q["original_provider_receipt_id"]+".json")).unlink()
        self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"], ["SOURCE_RECEIPT_NOT_FOUND"])

    def test_strict_input_no_raw_packet_or_client_permission(self):
        q = self.enroll(source())
        for field, value in (("monetary_permission",True),("receipt",source()),("source_path","/tmp/private"),
                             ("prediction_id","foreign"),("comparison",{})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                SituationRequest.from_dict({**q,field:value})

    def test_strict_input_identity_types_and_times(self):
        q = self.enroll(source())
        for value in (True,1.0,-1,2**31,"1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SituationRequest.from_dict({**q,"identity":{**q["identity"],"source_revision":value}})
        for field in ("kickoff","status_observed_at","request_at"):
            with self.subTest(field=field),self.assertRaises(ValueError):
                SituationRequest.from_dict({**q,field:"2030-01-01T12:00:00"})

    def test_frozen_request_and_isolated_return(self):
        q = self.enroll(source()); obj = SituationRequest.from_dict(q)
        with self.assertRaises(FrozenInstanceError): obj.intent="live"
        copied=obj.to_dict(); copied["identity"]["source_revision"]=10
        self.assertEqual(obj.identity.source_revision,1)
        self.assertNotEqual(obj.request_key, SituationRequest.from_dict({**q,"depth":"fast"}).request_key)

    def test_offset_and_dst_instants_use_utc(self):
        q = self.enroll(source())
        for field in ("kickoff","status_observed_at","request_at"):
            q[field]=datetime.fromisoformat(q[field]).astimezone(timezone(timedelta(hours=2))).isoformat()
        self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["phase"], "PREMATCH")
        # Same wall clock across DST has different actual instants.
        a=SituationRequest.from_dict({**q,"kickoff":"2030-10-27T03:30:00+03:00"})
        b=SituationRequest.from_dict({**q,"kickoff":"2030-10-27T03:30:00+02:00"})
        self.assertNotEqual(a.request_key,b.request_key)

    def test_source_json_duplicates_oversize_and_invalid(self):
        q=self.enroll(source()); path=self.receipts/(q["original_provider_receipt_id"]+".json")
        for raw in ('{"body":{},"body":{}}', 'x', '{"value":NaN}', ' '*65537):
            path.write_text(raw)
            self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["phase"],"HOLD")

    def test_symlink_receipt_is_rejected(self):
        q=self.enroll(source()); p=self.receipts/(q["original_provider_receipt_id"]+".json")
        other=self.folder/"outside.json"; p.rename(other)
        try:p.symlink_to(other)
        except OSError:
            # Windows without symlink privilege: exercise the same detected alias.
            with patch.object(Path,"is_symlink",return_value=True):
                self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"],["SOURCE_PATH_UNSAFE"])
            return
        self.assertEqual(chat_situation.execute_situation(q,clock=lambda: NOW)["reasons"],["SOURCE_PATH_UNSAFE"])

    def test_missing_db_not_created_and_core_never_called(self):
        q=self.enroll(source())
        with patch.object(chat_gateway,"execute_situation",functools.partial(chat_situation.execute_situation,clock=lambda: NOW)):
            with patch.object(chat_gateway,"Service",side_effect=AssertionError("CORE called")),patch.object(chat_gateway,"Repository",side_effect=AssertionError("DB opened")),patch.object(chat_store,"checkpoint",side_effect=AssertionError("checkpoint")):
                out=chat_gateway.execute("situation",q)
        self.assert_closed(out)
        self.assertFalse((self.folder/"canonical.sqlite").exists())

    def test_existing_canonical_ledger_bytes_and_records_survive_restart(self):
        p=self.folder/"canonical.sqlite"; r=Repository(str(p)); r.close(); before=p.read_bytes()
        q=self.enroll(source())
        for _ in range(2):
            with patch.object(chat_gateway,"execute_situation",functools.partial(chat_situation.execute_situation,clock=lambda: NOW)):
                chat_gateway.execute("situation",q)
            r=Repository(str(p),read_only=True)
            try:
                self.assertTrue(r.verify()); self.assertEqual(r.all("predictions"),[]); self.assertEqual(r.all("decisions"),[])
            finally:r.close()
        self.assertEqual(p.read_bytes(),before)

    def test_source_store_failure_is_hold_without_fallback(self):
        q=self.enroll(source())
        with patch.dict("os.environ",{"SEFIROT_STORE_URL":"configured"}),patch.object(chat_store,"request",side_effect=RuntimeError("secret must not escape")) as rpc:
            out=chat_situation.execute_situation(q,clock=lambda: NOW)
        self.assertEqual(out["reasons"],["SOURCE_STORE_UNAVAILABLE"])
        self.assertNotIn("secret",json.dumps(out)); rpc.assert_called_once()
        self.assert_closed(out)

    def test_status_action_only_reads_authenticated_source_rpc(self):
        obj=source(); q=request(obj)
        with patch.dict("os.environ",{"SEFIROT_STORE_URL":"configured"}),patch.object(chat_store,"request",return_value={"receipt":obj}) as rpc:
            out=chat_situation.execute_situation(q,clock=lambda: NOW)
        rpc.assert_called_once_with({"action":"situation_source","receipt_id":q["original_provider_receipt_id"]})
        self.assertEqual(out["phase"],"PREMATCH")

    def test_queue_situation_lease_and_legacy_dispatch_are_separate(self):
        q=self.enroll(source()); job={"id":"00000000-0000-0000-0000-000000000001","kind":"situation","attempt":2,"request":q}
        with patch.object(chat_queue,"request",side_effect=[{"job":job},{"completed":True}]) as rpc:
            with patch.object(chat_gateway,"execute_situation",functools.partial(chat_situation.execute_situation,clock=lambda: NOW)):
                self.assertTrue(chat_queue.process_one())
        final=rpc.call_args.args[0]
        self.assertEqual(final["attempt"],2); self.assertTrue(final["success"])
        self.assertEqual(final["response"]["phase"],"PREMATCH")

    def test_existing_sports_probe_queue_dispatch_and_completion_are_preserved(self):
        payload = {"queries": []}
        job = {"id": "00000000-0000-0000-0000-000000000001",
               "kind": "sports_probe", "request": payload, "attempt": 1}
        with (patch.object(chat_queue, "request", side_effect=[{"job": job}, {"completed": True,"id":job["id"],"attempts":1}]) as rpc,
              patch.object(chat_queue, "execute", return_value={"sports_only": True}) as run):
            self.assertTrue(chat_queue.process_one())
        run.assert_called_once_with("sports_probe", payload)
        self.assertTrue(rpc.call_args.args[0]["success"])
        self.assertEqual(rpc.call_args.args[0]["attempt"],1)
        self.assertEqual(rpc.call_args.args[0]["action"],"probe_complete")

    def test_unleased_queue_job_never_dispatches(self):
        q=self.enroll(source()); job={"id":"00000000-0000-0000-0000-000000000001","kind":"situation","request":q}
        with patch.object(chat_queue,"request",side_effect=[{"job":job},{"completed":True}]) as rpc,patch.object(chat_queue,"execute") as run:
            chat_queue.process_one(); run.assert_not_called()
        self.assertFalse(rpc.call_args.args[0]["success"])

    def test_mcp_typed_status_only_call(self):
        q=self.enroll(source())
        with patch.object(chat_gateway,"execute_situation",functools.partial(chat_situation.execute_situation,clock=lambda: NOW)):
            r=chat_mcp.process_rpc({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sefirot_situation","arguments":q}})
        self.assertFalse(r["result"]["isError"])
        self.assert_closed(json.loads(r["result"]["content"][0]["text"]))

    def test_cli_missing_source_is_hold_without_creating_database(self):
        q=self.enroll(source()); q["request_at"]=datetime.now(timezone.utc).isoformat()
        p=self.folder/"request.json"; p.write_text(json.dumps(q))
        (self.receipts/(q["original_provider_receipt_id"]+".json")).unlink()
        run=subprocess.run([sys.executable,str(ROOT/"scripts/chat_situation.py"),"--request",str(p)],
            capture_output=True,text=True,encoding="utf-8",timeout=15,
            env={**os.environ,"PYTHONIOENCODING":"cp1252"})
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)["phase"],"HOLD")
        self.assertIn("Следующее действие",json.loads(run.stdout)["summary"])
        self.assertFalse((self.folder/"canonical.sqlite").exists())


class LocalTransportTests(SituationHarness):
    def setUp(self):
        super().setUp()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),chat_mcp.MCPHandler)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.stack.enter_context(patch.object(chat_gateway,"execute_situation",functools.partial(chat_situation.execute_situation,clock=lambda: NOW)))

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)

    def post(self,path,payload,token=TEST_TOKEN):
        connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        raw=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
        try:
            connection.request("POST",path,body=raw,headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
            r=connection.getresponse();return r.status,json.loads(r.read())
        finally:connection.close()

    def test_rest_synthetic_ns_1h_ft_unknown(self):
        for s,phase in (("NS","PREMATCH"),("1H","LIVE_RESEARCH"),("FT","POSTMATCH"),("UNKNOWN","HOLD")):
            with self.subTest(s=s):
                q=self.enroll(source(s,kickoff=NOW+timedelta(minutes=4) if s=="NS" else NOW-timedelta(hours=2)))
                status,out=self.post("/v1/situation",q)
                self.assertEqual(status,200);self.assertEqual(out["data"]["phase"],phase);self.assert_closed(out["data"])

    def test_rest_authorization_injection_and_duplicate_fields(self):
        q=self.enroll(source())
        self.assertEqual(self.post("/v1/situation",q,token="wrong")[0],401)
        self.assertEqual(self.post("/v1/situation",{**q,"monetary_permission":True})[0],422)
        raw=json.dumps(q).encode(); raw=raw[:-1]+b',"intent":"live"}'
        self.assertEqual(self.post("/v1/situation",raw)[0],422)

    def test_real_mcp_http_dispatch_and_old_status_endpoint(self):
        q=self.enroll(source())
        status,out=self.post("/mcp",{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sefirot_situation","arguments":q}})
        self.assertEqual(status,200);self.assertFalse(out["result"]["isError"])
        connection=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        try:
            connection.request("GET","/v1/status",headers={"Authorization":"Bearer "+TEST_TOKEN})
            r=connection.getresponse();data=json.loads(r.read())
            self.assertEqual(r.status,200);self.assertTrue(data["data"]["ledger_integrity"])
        finally:connection.close()

    def test_mcp_duplicate_arguments_are_rejected_before_dispatch(self):
        raw = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sefirot_situation","arguments":{},"arguments":{}}}'
        with patch.object(chat_mcp, "call_tool") as dispatch:
            status, out = self.post("/mcp", raw)
        self.assertEqual(status, 400)
        self.assertEqual(out["error"]["code"], -32700)
        dispatch.assert_not_called()

    def test_nonascii_bearer_is_rejected_with_http_response(self):
        q = self.enroll(source())
        status, out = self.post("/v1/situation", q, token="\u00e9"*48)
        self.assertEqual(status, 401)
        self.assertEqual(out["error"], "UNAUTHORIZED")

    def test_capacity_429_is_bounded_and_no_core_fallback(self):
        q=self.enroll(source())
        for _ in range(4):self.assertTrue(chat_gateway.SITUATION_GATE.acquire(blocking=False))
        try:self.assertEqual(self.post("/v1/situation",q)[0],429)
        finally:
            for _ in range(4):chat_gateway.SITUATION_GATE.release()


if __name__ == "__main__":
    unittest.main()
