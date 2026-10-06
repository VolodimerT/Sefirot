import json, os, threading, urllib.parse, urllib.request
from flask import Flask, jsonify
BASE="https://www.fotmob.com/api/data/"
def get(path,params):
 u=BASE+path+"?"+urllib.parse.urlencode(params)
 r=urllib.request.Request(u,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT-research"})
 with urllib.request.urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
def scan():
 out={}
 for q in ["Podgorica","Lovcen","Pontypridd","Llantwit Major"]:
  try:out[q]=get("search/suggest",{"term":q,"hits":20,"lang":"en"})
  except Exception as e:out[q]={"error":type(e).__name__+":"+str(e)}
 return out
app=Flask(__name__);RESULT={"status":"BOOTING"}
def worker():
 global RESULT
 try:RESULT=scan()
 except Exception as e:RESULT={"error":type(e).__name__+":"+str(e)}
 print("SEFIROT_FOTMOB_SEARCH="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
threading.Thread(target=worker,daemon=True).start()
@app.get("/last")
def last():return jsonify(RESULT)
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
