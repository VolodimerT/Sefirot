import json, os, threading, urllib.parse, urllib.request
from flask import Flask, jsonify
BASE="https://www.fotmob.com/api/data/"
def get(path,params):
 u=BASE+path+"?"+urllib.parse.urlencode(params)
 r=urllib.request.Request(u,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT-research"})
 with urllib.request.urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
def summarize_team(t):
 out={"keys":list(t.keys())}
 fx=t.get("fixtures")
 out["fixtures_type"]=type(fx).__name__
 if isinstance(fx,dict):
  out["fixtures_keys"]=list(fx.keys())
  for k,v in fx.items():
   if isinstance(v,list):
    out["fixtures_"+k+"_n"]=len(v)
    out["fixtures_"+k+"_sample"]=v[:3]
   elif isinstance(v,dict):
    out["fixtures_"+k+"_keys"]=list(v.keys())[:20]
    for kk,vv in v.items():
     if isinstance(vv,list):
      out["fixtures_"+k+"_"+kk+"_n"]=len(vv)
      out["fixtures_"+k+"_"+kk+"_sample"]=vv[:3]
 overview=t.get("overview") or {}
 out["overview_keys"]=list(overview.keys())
 form=overview.get("teamForm")
 out["form_type"]=type(form).__name__
 if isinstance(form,dict):
  out["form_keys"]=list(form.keys())[:20]
  # find exact team id key
  out["form_2536"]=form.get("2536")
 return out
def scan():
 return summarize_team(get("teams",{"id":2536}))
app=Flask(__name__);RESULT={"status":"BOOTING"}
def worker():
 global RESULT
 try:RESULT=scan()
 except Exception as e:RESULT={"error":type(e).__name__+":"+str(e)}
 print("SEFIROT_FOTMOB_COMPACT="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
threading.Thread(target=worker,daemon=True).start()
@app.get("/last")
def last():return jsonify(RESULT)
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
