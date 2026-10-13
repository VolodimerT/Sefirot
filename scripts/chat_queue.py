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

SAFE_KINDS={"status","report","demo","capture","decide","result","stake_snapshot","sports_probe"}

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
        # Private, allowlisted diagnostics for malformed sports-only captures.
        # Provider errors and arbitrary strings are intentionally not disclosed.
        if kind == "capture" and type(exc) is ValueError:
            # Private diagnostic for sports-only input errors; no odds or credentials here.
            import re
            diagnostic = str(exc)
            if len(diagnostic) <= 160 and re.fullmatch(r"[A-Za-z0-9 _.,:;=+()\[\]'-]+", diagnostic):
                error = "CAPTURE_VALIDATION:" + diagnostic[:160]
            detail = diagnostic
            if detail in ("future or impossible evidence chronology", "history result chronology",
                          "duplicate history id", "invalid ISO timestamp", "unsupported operation",
                          "capture is no longer prematch", "history teams must differ",
                          "source enabled must be boolean", "unknown source",
                          "invalid evidence type", "target result must never be provided as history",
                          "duplicate source", "SPORTS_FACTS_INVALID", "history result chronology",
                          "history teams must differ", "invalid evidence id"):
                error="CAPTURE_VALIDATION:"+detail.replace(" ","_").upper()
            elif detail.startswith("fields missing="):
                error="CAPTURE_VALIDATION:INPUT_FIELDS"
            elif detail.startswith(("source reliability:", "match:", "home goals:", "away goals:")):
                error="CAPTURE_VALIDATION:INPUT_RANGE"
        if kind == "stake_snapshot" and isinstance(exc, ValueError):
            detail = str(exc)
            if detail == "STAKE_API_TOKEN is missing or invalid":
                error = "STAKE_TOKEN_MISSING_OR_INVALID"
            elif detail.startswith("stake provider HTTP "):
                error = "STAKE_PROVIDER_HTTP_ERROR"
            elif detail.startswith("fixture missing or ambiguous in Stake provider"):
                error = "STAKE_FIXTURE_MISSING_OR_AMBIGUOUS"
            elif detail.startswith("Stake") or detail.startswith("stake"):
                error = "STAKE_RESEARCH_GATE_CLOSED"
            elif "prematch" in detail or "sealed" in detail:
                error = "STAKE_PREMATCH_SEAL_REQUIRED"
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
