"""Temporary protected API-Football status probe through Supabase debug edge function."""
import os, json, urllib.request
if os.environ.get("SEFIROT_GATEWAY_STATUS_PROBE")=="1":
    try:
        # Token is intentionally kept inside the temporary probe and never printed.
        url="https://kxqpwgwihtjmqlcxgfxp.supabase.co/functions/v1/sefirot-debug-football?t="+"SFRDBG-20261004-x7K9p2"
        req=urllib.request.Request(url,headers={"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=30) as r:
            data=json.loads(r.read().decode())
        st=data.get("status") or {}
        resp=st.get("response") or {}
        out={"http":st.get("http"),"errors":st.get("errors"),"response":resp}
        print("SEFIROT_PROTECTED_FOOTBALL_STATUS="+json.dumps(out,separators=(",",":"),ensure_ascii=True),flush=True)
    except Exception as exc:
        print("SEFIROT_PROTECTED_FOOTBALL_STATUS="+json.dumps({"error":type(exc).__name__+":"+str(exc)},separators=(",",":")),flush=True)
