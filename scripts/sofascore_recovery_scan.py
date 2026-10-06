import json, os, threading, urllib.parse, urllib.request, unicodedata, re
from flask import Flask, jsonify
BASE="https://www.fotmob.com/api/data/"
TARGETS=[
 ("Podgorica - Lovcen",["Podgorica"],["Lovcen","Lovćen"]),
 ("Skjetten - Kongsvinger 2",["Skjetten"],["Kongsvinger 2","Kongsvinger II"]),
 ("Pontypridd - Llantwit",["Pontypridd"],["Llantwit Major","Llantwit"]),
 ("Braintree - Walton & Hersham",["Braintree","Braintree Town"],["Walton & Hersham","Walton and Hersham"]),
 ("Dartford - Ramsgate",["Dartford"],["Ramsgate"]),
 ("Maldon & Tiptree - Welling",["Maldon & Tiptree","Maldon and Tiptree"],["Welling","Welling United"]),
 ("Alfreton - FC United",["Alfreton","Alfreton Town"],["FC United","FC United of Manchester"]),
 ("Curzon Ashton - Redcar",["Curzon Ashton"],["Redcar","Redcar Athletic"]),
 ("Stockton - Bury",["Stockton","Stockton Town"],["Bury"]),
 ("Emley - Bamber Bridge",["Emley","AFC Emley"],["Bamber Bridge"]),
]
def get(path,params):
    u=BASE+path+"?"+urllib.parse.urlencode(params)
    r=urllib.request.Request(u,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT-research"})
    with urllib.request.urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
def cn(s):
    s=unicodedata.normalize("NFKD",str(s)).casefold()
    return "".join(c for c in s if c.isalnum())
def sc(s,aliases):
    c=cn(s); vals=[]
    for a in aliases:
      t=cn(a); vals.append(4 if c==t else 3 if len(c)>3 and len(t)>3 and (c in t or t in c) else 0)
    return max(vals+[0])
def scan():
    d=get("matches",{"date":"20261006"})
    flat=[]
    for lg in d.get("leagues",[]):
      for m in lg.get("matches",[]):
        flat.append({"league":lg.get("name"),"leagueId":lg.get("primaryId") or lg.get("id"),
                     "ccode":lg.get("ccode"),"id":m.get("id"),"time":m.get("time"),
                     "status":m.get("status"),"home":m.get("home"),"away":m.get("away")})
    hits=[]
    for label,ha,aa in TARGETS:
      ranked=[]
      for m in flat:
        h=(m.get("home") or {}).get("name","");a=(m.get("away") or {}).get("name","")
        hs,as_=sc(h,ha),sc(a,aa)
        if hs and as_:ranked.append((hs+as_,m))
      ranked.sort(key=lambda x:x[0],reverse=True)
      hits.append({"label":label,"match":ranked[0][1] if ranked else None,"score":ranked[0][0] if ranked else 0})
    # Probe one team endpoint for shape.
    sample=None
    for h in hits:
      if h["match"]:
        tid=(h["match"].get("home") or {}).get("id")
        if tid:
          try: sample=get("teams",{"id":tid})
          except Exception as e: sample={"error":type(e).__name__+":"+str(e)}
          break
    return {"status":"DONE","total_matches":len(flat),"hits":hits,"team_sample":sample}
app=Flask(__name__);RESULT={"status":"BOOTING"}
def worker():
 global RESULT
 try:RESULT=scan()
 except Exception as e:RESULT={"status":"ERROR","error":type(e).__name__+":"+str(e)}
 print("SEFIROT_FOTMOB_PROBE="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
@app.get("/health")
def h():return jsonify({"ok":True,"status":RESULT.get("status")})
@app.get("/last")
def l():return jsonify(RESULT)
threading.Thread(target=worker,daemon=True).start()
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
