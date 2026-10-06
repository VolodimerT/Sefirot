import json, os, threading, urllib.parse, urllib.request
from flask import Flask, jsonify

BASE="https://openfootapi.com/v1"
Q=["Podgorica","Lovcen","Skjetten","Kongsvinger","Pontypridd","Llantwit Major","Braintree","Walton Hersham","Dartford","Ramsgate","Maldon Tiptree","Welling United","Alfreton Town","FC United Manchester","Curzon Ashton","Redcar Athletic","Stockton Town","Bury","Emley","Bamber Bridge"]
HEAD={"Accept":"application/json","Authorization":"Bearer of_demo_openfootapi_docs","User-Agent":"SEFIROT/2.4.2 research"}

def get(path):
    r=urllib.request.Request(BASE+path,headers=HEAD)
    with urllib.request.urlopen(r,timeout=20) as x:
        return json.loads(x.read().decode())

def scan():
    out={"status":"RUNNING","search":{},"date":None}
    try:
        out["date"]=get("/matches?date=2026-10-06")
    except Exception as e:
        out["date_error"]=type(e).__name__+":"+str(e)
    for q in Q:
        try:
            out["search"][q]=get("/search?q="+urllib.parse.quote(q))
        except Exception as e:
            out["search"][q]={"error":type(e).__name__+":"+str(e)}
    out["status"]="DONE"
    return out

app=Flask(__name__); RESULT={"status":"BOOTING"}
def worker():
    global RESULT
    try: RESULT=scan()
    except Exception as e: RESULT={"status":"ERROR","error":type(e).__name__+":"+str(e)}
    print("SEFIROT_OPENFOOT_PROBE="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
@app.get("/health")
def health(): return jsonify({"ok":True,"status":RESULT.get("status")})
@app.get("/last")
def last(): return jsonify(RESULT)
threading.Thread(target=worker,daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
