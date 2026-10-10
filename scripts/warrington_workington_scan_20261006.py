from __future__ import annotations
import json, os, time as _time, urllib.parse, urllib.request, threading, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, jsonify
from sefirot.contracts import Policy
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.market_grid import create_grid
from sefirot.markets import fair_odds

BASE="https://www.fotmob.com/api/data/"; DATE="20261006"; SOURCE="fotmob-unofficial-research"
TARGETS=[("Dartford","Ramsgate"),("Sportivo Ameliano","Rubio"),("Colombia","Peru")]
TESTS=[
 {"label":"DART_RAMSGATE_UNDER_1_5","home":"Dartford","market":{"kind":"TEAM_TOTAL","side":"AWAY_UNDER","line":1.5},"odds":1.43},
 {"label":"DART_RAMSGATE_OVER_1","home":"Dartford","market":{"kind":"TEAM_TOTAL","side":"AWAY_OVER","line":1.0},"odds":1.74},
 {"label":"DART_HOME_UNDER_1_5","home":"Dartford","market":{"kind":"TEAM_TOTAL","side":"HOME_UNDER","line":1.5},"odds":2.06},
 {"label":"DART_BTTS_YES","home":"Dartford","market":{"kind":"BTTS","side":"YES"},"odds":1.56},
 {"label":"DART_TOTAL_UNDER_2_5","home":"Dartford","market":{"kind":"TOTAL","side":"UNDER","line":2.5},"odds":2.23},
 {"label":"DART_X2","home":"Dartford","market":{"kind":"DOUBLE_CHANCE","side":"X2"},"odds":1.96},
 {"label":"DART_AWAY_WIN","home":"Dartford","market":{"kind":"1X2","side":"AWAY"},"odds":3.62},

 {"label":"AMEL_RUBIO_OVER_1","home":"Sportivo Ameliano","market":{"kind":"TEAM_TOTAL","side":"AWAY_OVER","line":1.0},"odds":1.97},
 {"label":"AMEL_RUBIO_OVER_1_5","home":"Sportivo Ameliano","market":{"kind":"TEAM_TOTAL","side":"AWAY_OVER","line":1.5},"odds":2.97},
 {"label":"AMEL_HOME_UNDER_1_5","home":"Sportivo Ameliano","market":{"kind":"TEAM_TOTAL","side":"HOME_UNDER","line":1.5},"odds":1.56},
 {"label":"AMEL_BTTS_YES","home":"Sportivo Ameliano","market":{"kind":"BTTS","side":"YES"},"odds":1.84},
 {"label":"AMEL_TOTAL_OVER_2_5","home":"Sportivo Ameliano","market":{"kind":"TOTAL","side":"OVER","line":2.5},"odds":2.09},
 {"label":"AMEL_TOTAL_UNDER_2_5","home":"Sportivo Ameliano","market":{"kind":"TOTAL","side":"UNDER","line":2.5},"odds":1.69},
 {"label":"AMEL_X2","home":"Sportivo Ameliano","market":{"kind":"DOUBLE_CHANCE","side":"X2"},"odds":1.61},
 {"label":"AMEL_AWAY_WIN","home":"Sportivo Ameliano","market":{"kind":"1X2","side":"AWAY"},"odds":3.20},

 {"label":"COL_PERU_OVER_1","home":"Colombia","market":{"kind":"TEAM_TOTAL","side":"AWAY_OVER","line":1.0},"odds":4.70},
 {"label":"COL_HOME_OVER_1_5","home":"Colombia","market":{"kind":"TEAM_TOTAL","side":"HOME_OVER","line":1.5},"odds":1.66},
 {"label":"COL_BTTS_YES","home":"Colombia","market":{"kind":"BTTS","side":"YES"},"odds":2.41},
 {"label":"COL_TOTAL_OVER_2_5","home":"Colombia","market":{"kind":"TOTAL","side":"OVER","line":2.5},"odds":2.07},
 {"label":"COL_TOTAL_UNDER_2_5","home":"Colombia","market":{"kind":"TOTAL","side":"UNDER","line":2.5},"odds":1.75},
 {"label":"COL_X2","home":"Colombia","market":{"kind":"DOUBLE_CHANCE","side":"X2"},"odds":2.95},
 {"label":"COL_AWAY_WIN","home":"Colombia","market":{"kind":"1X2","side":"AWAY"},"odds":8.55}
]

def utcnow(): return datetime.now(timezone.utc)
def parse_iso(s): return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(timezone.utc)
def get(path,params):
    url=BASE+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT/2.4.2 research"})
    with urllib.request.urlopen(req,timeout=25) as r: data=json.loads(r.read().decode())
    _time.sleep(.03); return data

def find_targets():
    d=get("matches",{"date":DATE}); out={}
    for league in d.get("leagues") or []:
        lid=league.get("primaryId") or league.get("id")
        for m in league.get("matches") or []:
            hn=(m.get("home") or {}).get("name") or ""; an=(m.get("away") or {}).get("name") or ""
            for a,b in TARGETS:
                if a.casefold() in hn.casefold() and b.casefold() in an.casefold():
                    out[a]={"match":m,"league":league,"league_id":lid}
    return out

def team_page(tid,cache):
    if tid not in cache: cache[tid]=get("teams",{"id":tid})
    return cache[tid]

def history_for(target,league_id,cache):
    merged={}; cutoff=utcnow(); counts=[]
    for tid in (int(target["home"]["id"]),int(target["away"]["id"])):
        cnt=0
        fx=(((team_page(tid,cache).get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or [])
        for e in fx:
            st=e.get("status") or {}; tr=e.get("tournament") or {}
            if not st.get("finished"): continue
            if int(tr.get("leagueId") or -1)!=int(league_id): continue
            try: ko=parse_iso(st["utcTime"])
            except: continue
            if ko>=cutoff or (cutoff-ko).days>1200: continue
            h=e.get("home") or {}; a=e.get("away") or {}
            if not isinstance(h.get("score"),(int,float)) or not isinstance(a.get("score"),(int,float)): continue
            cnt+=1
            merged[int(e["id"])]={
              "id":f"fotmob:event:{e['id']}","home":h.get("name"),"away":a.get("name"),
              "league":f"fotmob:league:{league_id}","kickoff":ko.isoformat(),
              "finished_at":(ko+timedelta(hours=3)).isoformat(),"received_at":cutoff.isoformat(),
              "home_goals":int(h["score"]),"away_goals":int(a["score"]),"source_id":SOURCE,
              "competition_profile":"LOWER"
            }
        counts.append(cnt)
    return sorted(merged.values(),key=lambda x:x["kickoff"]),counts

def sports(target,lid,hist):
    asof=utcnow().isoformat(); ko=parse_iso((target.get("status") or {}).get("utcTime"))
    match={"id":f"fotmob:event:{target['id']}","home":target["home"]["name"],"away":target["away"]["name"],
           "league":f"fotmob:league:{lid}","kickoff":ko.isoformat(),"sport":"football",
           "format":"REGULATION_90","competition_profile":"LOWER"}
    ev=[]
    for k,v in (("home_team",match["home"]),("away_team",match["away"]),("format","REGULATION_90")):
        ev.append({"id":f"{match['id']}:{k}","key":k,"value":v,"kind":"FACT","source_id":SOURCE,
                   "published_at":asof,"received_at":asof,"observed_at":asof,"critical":True,"supports":[]})
    return {"match":match,"as_of":asof,
            "sources":[{"id":SOURCE,"independence_group":"fotmob-direct-json","reliability":.82,"enabled":True}],
            "evidence":ev,"history":hist}

def entry_threshold(probs,edge=.05):
    w,p,l=probs
    return None if w<=0 else 1+(l+edge)/w

def eval_one(item,hist,counts,test):
    t=item["match"]; lid=item["league_id"]; market=test["market"]
    tag=hashlib.sha1(json.dumps(market,sort_keys=True).encode()).hexdigest()[:8]
    repo=Repository(Path("/tmp")/f"single_{t['id']}_{tag}.sqlite")
    try:
        pol=Policy(); pred=Service(repo,pol).capture(sports(t,lid,hist),[market])
        grid=create_grid(pred,pol,pred["sealed_at"])
        row=None
        for r in grid["candidates"]:
            if r["market"]==market: row=r; break
        if row is None: raise RuntimeError("candidate_missing")
        raw=row["raw"]; stress=row["stress_probabilities"]; odds=float(test["odds"])
        stress_evs=[p[0]*(odds-1)-p[2] for p in stress]
        return {
          "label":test["label"],"market":market,"odds":odds,
          "p_win":round(raw[0],4),"p_push":round(raw[1],4),"p_loss":round(raw[2],4),
          "fair":round(fair_odds(raw[0],raw[1]),3),
          "base_ev":round(raw[0]*(odds-1)-raw[2],4),
          "stress_ev_min":round(min(stress_evs),4),"stress_ev_max":round(max(stress_evs),4),
          "entry5":round(max(entry_threshold(x,.05) for x in stress if x[0]>0),3),
          "selection_status":row["selection_status"],
          "loss_scores":[{"score":f"{x['home']}:{x['away']}","p":round(float(x.get("probability",x.get("p",0))),4)}
                         for x in row["death_test"]["top_score_losses"][:4]],
          "history_n":len(hist),"team_counts":counts,
          "issues":[x["code"] for x in pred["issues"]],"rates":pred["model"]["rates"]
        }
    finally: repo.close()

def scan():
    cache={}; items=find_targets(); prep={}
    for h,item in items.items():
        prep[h]=history_for(item["match"],item["league_id"],cache)
    out=[]
    for test in TESTS:
        item=items[test["home"]]; hist,counts=prep[test["home"]]
        try: out.append(eval_one(item,hist,counts,test))
        except Exception as e: out.append({"label":test["label"],"error":type(e).__name__+":"+str(e)})
    return {"status":"DONE","results":out}

app=Flask(__name__); RESULT={"status":"BOOTING"}
def worker():
    global RESULT
    try: RESULT=scan()
    except Exception as e: RESULT={"status":"ERROR","error":type(e).__name__+":"+str(e)}
    print("SEFIROT_TRIPLE_SCAN="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
threading.Thread(target=worker,daemon=True).start()
@app.get("/last")
def last(): return jsonify(RESULT)
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
