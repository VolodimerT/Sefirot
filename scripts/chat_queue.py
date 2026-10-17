"""Private ChatGPT<->Supabase<->SEFIROT model job bridge.

Jobs are never wagers. The connected Supabase tool can enqueue a trusted
research request; this background worker routes it to the original Service.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from chat_store import DurableStoreError, request
from chat_gateway import execute, read_only_mode, run_demo

SAFE_KINDS={"status","report","demo","capture","decide","result","sports_probe","situation"}
_process_lock = Lock()
_lifecycle_lock = Lock()
_state_lock = Lock()
_stop = Event()
_thread = None
_state = {"last_poll_at": None, "last_completed_at": None,
          "completed_jobs": 0, "last_error": None}


def sports_only_mode():
    mode = os.environ.get("SEFIROT_CHAT_JOB_WORKER_MODE", "canonical")
    if mode not in ("canonical", "sports_probe"):
        raise RuntimeError("INVALID_CHAT_JOB_WORKER_MODE")
    # Explicitly enable only this research consumer; public CORE remains read-only.
    if mode == "sports_probe" and not read_only_mode():
        raise RuntimeError("SPORTS_WORKER_REQUIRES_READ_ONLY_CORE")
    return mode == "sports_probe"


def worker_status():
    sports = sports_only_mode()
    with _state_lock:
        state = dict(_state)
    return {**state, "mode": "sports_probe" if sports else "canonical",
            "running": bool(_thread and _thread.is_alive()),
            "stopping": _stop.is_set(), "shared_budget_required": True,
            "provider_quota": "NOT_VERIFIED", "monetary_permission": False,
            "execution_enabled": False}


def _now():
    return datetime.now(timezone.utc).isoformat()

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
    sports = sports_only_mode()
    if read_only_mode() and not sports:return False
    # In-process callers cannot accidentally run multiple consumers. PostgreSQL
    # SKIP LOCKED + the shared gateway reservation serialize cross-process work.
    if not _process_lock.acquire(blocking=False):return False
    try:
        with _state_lock:
            _state["last_poll_at"] = _now()
        return _process_one(sports)
    finally:
        _process_lock.release()


def _process_one(sports):
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
        if sports and kind != "sports_probe":
            raise ValueError("SPORTS_ONLY_WORKER")
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
            if sports:
                # Reuse the guarded collector. Never restore/write the CORE
                # ledger or enable capture/decision/result HTTP operations.
                from chat_sports_probe import collect
                result=collect(payload)
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
    with _state_lock:
        _state["last_completed_at"] = _now()
        _state["completed_jobs"] += 1
        _state["last_error"] = error
    print("SEFIROT_CHAT_JOB_"+("DONE" if success else "PASS")+
          " id="+str(uid),flush=True)
    return True

def run():
    sports = sports_only_mode()
    if read_only_mode() and not sports:return
    idle=0
    while not _stop.is_set():
        try:
            worked=process_one()
            idle=0 if worked else min(idle+1,3)
            _stop.wait(4 if worked else [12,20,35,60][idle])
        except Exception:
            with _state_lock:
                _state["last_error"] = "QUEUE_UNAVAILABLE"
            print("SEFIROT_CHAT_JOB_QUEUE_UNAVAILABLE",flush=True)
            _stop.wait(60)

def start():
    global _thread
    sports = sports_only_mode()
    if read_only_mode() and not sports:return False
    with _lifecycle_lock:
        if _thread and _thread.is_alive():return True
        _stop.clear()
        _thread=Thread(target=run,daemon=True,name="sefirot-chat-job-worker")
        _thread.start()
    return True


def stop(timeout=25):
    _stop.set()
    with _lifecycle_lock:
        thread = _thread
    if thread:
        thread.join(timeout=timeout)
