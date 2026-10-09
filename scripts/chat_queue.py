"""Private ChatGPT<->Supabase<->SEFIROT model job bridge.

Jobs are never wagers. The connected Supabase tool can enqueue a trusted
research request; this background worker routes it to the original Service.
"""
from __future__ import annotations
import json
import time
from threading import Thread
from chat_store import request
from chat_gateway import execute, run_demo

SAFE_KINDS={"status","report","demo","capture","decide","result"}

def process_one() -> bool:
    envelope=request({"action":"claim"})
    job=envelope.get("job")
    if job is None:return False
    uid=job.get("id")
    kind=job.get("kind")
    payload=job.get("request")
    success=False
    result=None
    error=None
    try:
        if kind not in SAFE_KINDS or not isinstance(payload,dict):
            raise ValueError("INVALID_RESEARCH_JOB")
        if kind in ("status","report","demo") and payload:
            raise ValueError("READ_ONLY_JOB_ARGS_FORBIDDEN")
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
    acknowledgment=request({"action":"complete","id":uid,"success":success,
                             "response":result,"error":error})
    if acknowledgment.get("completed") is not True:
        raise RuntimeError("CHAT_JOB_NOT_ACKNOWLEDGED")
    print("SEFIROT_CHAT_JOB_"+("DONE" if success else "PASS")+
          " id="+str(uid),flush=True)
    return True

def run():
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
    Thread(target=run,daemon=True,name="sefirot-chat-job-worker").start()
