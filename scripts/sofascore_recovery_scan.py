import json, os, threading, urllib.parse, urllib.request
from flask import Flask, jsonify
BASE="https://www.fotmob.com/api/data/"
def get(path,params):
    u=BASE+path+"?"+urllib.parse.urlencode(params)
    r=urllib.request.Request(u,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT-research"})
    with urllib.request.urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
def scan():
    t=get("teams",{"id":2536})
    def shape(x,depth=0):
        if depth>2:return type(x).__name__
        if isinstance(x,dict):return {k:shape(v,depth+1) for k,v in list(x.items())[:30]}
        if isinstance(x,list):return {"type":"list","len":len(x),"first":shape(x[0],depth+1) if x else None}
        return type(x).__name__
    out={"keys":list(t.keys()),"overview":t.get("overview"),"fixtures_shape":shape(t.get("fixtures"))}
    return out
app=Flask(__name__);RESULT={"status":"BOOTING"}
def worker():
 global RESULT
 try:RESULT=scan()
 except Exception as e:RESULT={"error":type(e).__name__+":"+str(e)}
 print("SEFIROT_FOTMOB_TEAM_SHAPE="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
@app.get("/last")
def l():return jsonify(RESULT)
threading.Thread(target=worker,daemon=True).start()
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
