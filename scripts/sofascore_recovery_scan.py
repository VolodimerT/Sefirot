import json, os, threading, urllib.parse, urllib.request
from flask import Flask, jsonify
BASE="https://www.fotmob.com/api/data/"
def get(path,params):
 u=BASE+path+"?"+urllib.parse.urlencode(params)
 r=urllib.request.Request(u,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT-research"})
 with urllib.request.urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
def team(tid):
 d=get("teams",{"id":tid}); fx=((d.get("fixtures") or {}).get("allFixtures") or {})
 def mini(x):
  if not isinstance(x,dict):return None
  return {"id":x.get("id"),"home":(x.get("home") or {}).get("name"),"away":(x.get("away") or {}).get("name"),
          "utc":(x.get("status") or {}).get("utcTime"),"notStarted":x.get("notStarted"),
          "tournament":(x.get("tournament") or {}).get("name"),"leagueId":(x.get("tournament") or {}).get("leagueId")}
 return {"id":tid,"name":(d.get("details") or {}).get("name"),"next":mini(fx.get("nextMatch")),
         "last":mini(fx.get("lastMatch")),"tail":[mini(x) for x in (fx.get("fixtures") or [])[-8:]]}
def scan():return {"podgorica":team(677268),"lovcen":team(89513),"pontypridd":team(321094)}
app=Flask(__name__);RESULT={"status":"BOOTING"}
def worker():
 global RESULT
 try:RESULT=scan()
 except Exception as e:RESULT={"error":type(e).__name__+":"+str(e)}
 print("SEFIROT_MISSING_FIXTURES="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
threading.Thread(target=worker,daemon=True).start()
@app.get("/last")
def last():return jsonify(RESULT)
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
