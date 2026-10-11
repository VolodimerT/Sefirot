"""Repeatable synthetic warm loopback status measurements, never a model scorecard."""
from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
from threading import Thread
from time import perf_counter
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts"),str(ROOT)]
from sefirot.contracts import Policy,canonical,digest
from sefirot.engine import code_hash,model_code_hash
import chat_gateway
from chat_situation import execute_situation
from research.situational_v1 import route_fixture


def percentiles(values):
    ordered=sorted(values)
    return {"n":len(ordered),**{f"p{p}_ms":round(ordered[math.ceil(p/100*len(ordered))-1],3) for p in (50,95,99)}}


def run(n=100):
    if type(n) is not int or n<100:raise ValueError("N >=100 per class required")
    now=datetime.now(timezone.utc)
    token="synthetic-status-benchmark-bearer-000000000000000000"
    key="synthetic-status-benchmark-source-key-00000000000000"
    cases=[("EARLY_NS_DEEP","NS",7200,"PREMATCH","DEEP"),
           ("NEAR_NS_FAST","NS",240,"PREMATCH","FAST"),
           ("LIVE_1H_FAST","1H",-1800,"LIVE_RESEARCH","FAST"),
           ("FINISHED_FT","FT",-7200,"POSTMATCH","FAST"),
           ("UNKNOWN_HOLD","UNKNOWN",240,"HOLD","NONE")]
    report={"schema":"situation-warm-synthetic-latency-v1","at":now.isoformat(),
        "synthetic":True,"external_api_calls":0,"machine":platform.platform(),
        "python":platform.python_version(),"source":"LOCAL_SIGNED_SYNTHETIC_RECEIPTS",
        "scope":"LOOPBACK_HTTP_AND_STATUS_DISPATCH_WITHOUT_CORE_OR_QUEUE",
        "cold_start":"NOT_MEASURED","production_slo_validated":False,
        "core_compute":"NOT_INVOKED","arena":"NOT_INVOKED","upstream_api":"NOT_INVOKED",
        "queue_latency":"NOT_MEASURED","model_hash":model_code_hash(),
        "code_hash":code_hash(),"policy_hash":Policy().fingerprint,"classes":[]}
    with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
        root=Path(temp).resolve()
        stack.enter_context(patch.dict(os.environ,{"SEFIROT_STORE_URL":"", "SEFIROT_SITUATION_RECEIPTS":str(root),
            "SEFIROT_SITUATION_SOURCE_KEY":key,"SEFIROT_SITUATION_ALLOW_SYNTHETIC":"1",
            "SEFIROT_BRIDGE_TOKEN":token,"SEFIROT_BRIDGE_DB":str(root/"must-not-exist.sqlite")}))
        stack.enter_context(patch.object(chat_gateway,"execute_situation",lambda q:execute_situation(q,clock=lambda:now)))
        server=ThreadingHTTPServer(("127.0.0.1",0),chat_gateway.Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for label,status,delta,phase,depth in cases:
                body={"schema":"situation-source-receipt-v1","fixture_id":"synthetic:benchmark:"+label,
                    "source_id":"synthetic-benchmark","source_revision":1,"provider_status":status,
                    "kickoff":(now+timedelta(seconds=delta)).isoformat(),
                    "status_observed_at":(now-timedelta(seconds=2)).isoformat(),
                    "status_received_at":(now-timedelta(seconds=1)).isoformat(),"origin":"SYNTHETIC_TEST_ONLY"}
                envelope={"body":body,"collector_signature":hmac.new(key.encode(),canonical(body).encode(),hashlib.sha256).hexdigest()}
                receipt=digest(body);(root/(receipt+".json")).write_text(json.dumps(envelope),encoding="utf-8")
                q={"fixture_id":body["fixture_id"],"provider_status":status,"kickoff":body["kickoff"],
                    "status_observed_at":body["status_observed_at"],"request_at":now.isoformat(),"intent":"auto","depth":"auto",
                    "original_provider_receipt_id":receipt,"identity":{"source_id":body["source_id"],"source_revision":1,
                    "receipt_hash":receipt,"model_hash":model_code_hash()}}
                raw=json.dumps(q).encode();latency=[];processing=[];baseline=[];example=None
                for _ in range(n):
                    start=perf_counter()
                    route=route_fixture({"fixture_id":body["fixture_id"],"source_id":body["source_id"],"status":status,
                        "kickoff":body["kickoff"],"status_received_at":body["status_received_at"],
                        "status_observed_at":body["status_observed_at"]},at=now.isoformat())
                    baseline.append((perf_counter()-start)*1000)
                    assert ("POSTMATCH" if route["mode"]=="POSTMATCH_RECAP" else route["mode"])==phase
                    start=perf_counter();connection=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
                    try:
                        connection.request("POST","/v1/situation",body=raw,headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
                        response=connection.getresponse();out=json.loads(response.read());assert response.status==200
                    finally:connection.close()
                    latency.append((perf_counter()-start)*1000);example=out["data"]
                    assert (example["phase"],example["depth"])==(phase,depth)
                    assert example["monetary_permission"] is False and example["core_invoked"] is False
                    processing.append(example["measured_processing_ms"])
                report["classes"].append({"class":label,"phase":phase,"depth":depth,"receipt_hash":receipt,
                    "request_hash":digest(q),"warm_http":percentiles(latency),"warm_processing":percentiles(processing),
                    "unattested_router_function":percentiles(baseline),
                    "comparison_limit":"DIRECT_FUNCTION_AND_HTTP_HAVE_DIFFERENT_BOUNDARIES; NO_SPEEDUP_CLAIM",
                    "identical_phase_and_permissions":True,"example":example})
            assert not (root/"must-not-exist.sqlite").exists()
        finally:server.shutdown();server.server_close();thread.join(timeout=5)
    return report


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);parser.add_argument("--n",type=int,default=100)
    args=parser.parse_args();result=run(args.n)
    with args.output.open("x",encoding="utf-8") as handle:json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False);handle.write("\n")
    print(json.dumps({"output":str(args.output),"n_per_class":args.n,"synthetic":True,"production_slo_validated":False}))
