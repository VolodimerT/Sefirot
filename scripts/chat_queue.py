"""Private ChatGPT<->Supabase<->SEFIROT model job bridge.

Jobs are never wagers. The connected Supabase tool can enqueue a trusted
research request; this background worker routes it to the original Service.
"""
from __future__ import annotations
import json
import time
from threading import Thread
from chat_store import DurableStoreError, request
from chat_gateway import execute, read_only_mode, run_demo

SAFE_KINDS={"status","report","demo","capture","decide","result","sports_probe","situation"}

def _complete_probe(payload):
    # Only this fenced, idempotent operation is replayable. Never retry claim,
    # execute, provider fetch, checkpoint, or a legacy completion here.
    for attempt in range(2):
        try:
            acknowledgment = request(payload)
            break
        except DurableStoreError as exc:
            if attempt or not exc.retryable:
                raise
    if (acknowledgment.get("completed") is not True
            or acknowledgment.get("id") != payload["id"]
            or type(acknowledgment.get("attempts")) is not int
            or acknowledgment["attempts"] != payload["attempt"]):
        raise RuntimeError("CHAT_PROBE_NOT_ACKNOWLEDGED")
    return acknowledgment

def process_one() -> bool:
    if read_only_mode():return False
    envelope=request({"action":"claim"})
    job=envelope.get("job")
    if job is None:return False
    uid=job.get("id")
    kind=job.get("kind")
    payload=job.get("request")
    if kind == "sports_probe" and (type(job.get("attempt")) is not int
                                   or not 1 <= job["attempt"] <= 3):
        # An unleased completion would bypass fencing. Leave it for review.
        raise RuntimeError("PROVIDER_FETCH_LEASE_REQUIRED")
    success=False
    result=None
    error=None
    try:
        if kind not in SAFE_KINDS or not isinstance(payload,dict):
            raise ValueError("INVALID_RESEARCH_JOB")
        if kind == "situation" and (type(job.get("attempt")) is not int or not 1 <= job["attempt"] <= 3):
            raise ValueError("INVALID_SITUATION_LEASE")
        if kind in ("status","report","demo") and payload:
            raise ValueError("READ_ONLY_JOB_ARGS_FORBIDDEN")
        # The durable queue reclaims expired RUNNING leases. A provider fetch
        # might already have succeeded before its completion acknowledgement
        # was lost. Never spend quota again to reconstruct that missing receipt.
        if kind == 'sports_probe' and job['attempt'] != 1:
            error='PROVIDER_FETCH_RETRY_REQUIRES_REVIEW'
        else:
            result=run_demo() if kind=="demo" else execute(kind,payload)
            # Limits private job payload size without altering a canonical decision.
            serialized=json.dumps(result,ensure_ascii=False,allow_nan=False)
            if len(serialized.encode("utf-8"))>850000:
                raise ValueError("RESPONSE_TOO_LARGE")
            success=True
    except (ValueError,TypeError,KeyError) as exc:
        error="INPUT_VALIDATION_OR_PREMATCH_GATE"
    except Exception:
        error="RESEARCH_RUNNER_ERROR"
    result=result if success else None
    complete={"action":"complete","id":uid,"success":success,
              "response":result,"error":error}
    if kind in ("situation", "sports_probe"):
        complete["attempt"]=job.get("attempt")
    if kind == "sports_probe":
        complete["action"]="probe_complete"
        acknowledgment=_complete_probe(complete)
    else:
        acknowledgment=request(complete)
    if acknowledgment.get("completed") is not True:
        raise RuntimeError("CHAT_JOB_NOT_ACKNOWLEDGED")
    print("SEFIROT_CHAT_JOB_"+("DONE" if success else "PASS")+
          " id="+str(uid),flush=True)
    return True

def run():
    if read_only_mode():return
    idle=0
    while True:
        try:
            worked=process_one()
            idle=0 if worked else min(idle+1,3)
            time.sleep(4 if worked else [12,20,35,60][idle])
        except Exception:
            print("SEFIROT_CHAT_JOB_QUEUE_UNAVAILABLE",flush=True)
            time.sleep(60)

def start():
    if read_only_mode():return False
    Thread(target=run,daemon=True,name="sefirot-chat-job-worker").start()
    return True
