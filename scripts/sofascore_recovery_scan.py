from __future__ import annotations
import json, math, os, re, threading, time as _time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from flask import Flask, jsonify

from sefirot.contracts import Policy
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.market_grid import create_grid
from sefirot.builder_research import create_builder_grid
from sefirot.markets import fair_odds

BASE="https://www.fotmob.com/api/data/"
DATE="20261006"
SOURCE="fotmob-unofficial-research"
POOL=[
 {"kind":"1X2","side":"HOME"},
 {"kind":"DOUBLE_CHANCE","side":"1X"},
 {"kind":"DNB","side":"HOME"},
 {"kind":"HANDICAP","side":"HOME","line":-0.5},
 {"kind":"TOTAL","side":"OVER","line":2.5},
 {"kind":"BTTS","side":"YES"},
 {"kind":"TEAM_TOTAL","side":"HOME_OVER","line":1.5},
]
TARGETS=[
 ("2 Skjetten - Kongsvinger 2",5144585,{"kind":"HANDICAP","side":"HOME","line":-1.0}),
 ("4 Braintree - Walton & Hersham",5907602,{"kind":"TEAM_TOTAL","side":"HOME_OVER","line":1.5}),
 ("5 Dartford - Ramsgate",5948104,{"kind":"TOTAL","side":"OVER","line":2.5}),
 ("6 Maldon & Tiptree - Welling",5948106,{"kind":"TOTAL","side":"OVER","line":3.0}),
 ("7 Alfreton - FC United",5949281,{"builder":[{"kind":"DOUBLE_CHANCE","side":"1X"},{"kind":"TOTAL","side":"OVER","line":1.5}]}),
 ("8 Curzon Ashton - Redcar",5949279,{"kind":"BTTS","side":"YES"}),
 ("9 Stockton - Bury",5949274,{"kind":"TEAM_TOTAL","side":"AWAY_OVER","line":1.5}),
 ("10 Emley - Bamber Bridge",5949278,{"kind":"TOTAL","side":"OVER","line":2.5}),
]
SMALL_MAP={
 "cornerkicks":"CORNERS","corners":"CORNERS",
 "totalshots":"SHOTS","shots":"SHOTS",
 "shotsongoal":"SOT","shotsontarget":"SOT",
 "fouls":"FOULS","yellowcards":"CARDS",
}

def utcnow(): return datetime.now(timezone.utc)
def parse_iso(s): return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(timezone.utc)
def get(path,params):
    url=BASE+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT/2.4.2 research"})
    with urllib.request.urlopen(req,timeout=25) as r:
        if r.status!=200: raise RuntimeError("FOTMOB_HTTP_"+str(r.status))
        data=json.loads(r.read().decode())
    if not isinstance(data,dict): raise RuntimeError("FOTMOB_INVALID_JSON")
    _time.sleep(.04)
    return data

def all_matches():
    d=get("matches",{"date":DATE})
    out={}
    for league in d.get("leagues") or []:
        for m in league.get("matches") or []:
            if m.get("id"):
                out[int(m["id"])]={"match":m,"league":league}
    return out

def team_page(tid,cache):
    if tid not in cache: cache[tid]=get("teams",{"id":tid})
    return cache[tid]

def history_for(target,league_id,cache):
    ids=[target["home"]["id"],target["away"]["id"]]
    merged={}
    cutoff=utcnow()
    for tid in ids:
        d=team_page(int(tid),cache)
        fixtures=(((d.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or [])
        for e in fixtures:
            status=e.get("status") or {}
            tourn=e.get("tournament") or {}
            if not status.get("finished"): continue
            if int(tourn.get("leagueId") or -1)!=int(league_id): continue
            try: ko=parse_iso(status["utcTime"])
            except Exception: continue
            if ko>=cutoff or (cutoff-ko).days>730: continue
            h=e.get("home") or {};a=e.get("away") or {}
            if not isinstance(h.get("score"),(int,float)) or not isinstance(a.get("score"),(int,float)): continue
            merged[int(e["id"])]={
              "id":f"fotmob:event:{e['id']}","home":h.get("name"),"away":a.get("name"),
              "league":f"fotmob:league:{league_id}","kickoff":ko.isoformat(),
              "finished_at":(ko+timedelta(hours=3)).isoformat(),"received_at":cutoff.isoformat(),
              "home_goals":int(h["score"]),"away_goals":int(a["score"]),"source_id":SOURCE,
              "competition_profile":"LOWER"
            }
    return sorted(merged.values(),key=lambda x:x["kickoff"])

def sports(target,league_id,history):
    asof=utcnow().isoformat()
    ko=parse_iso((target.get("status") or {}).get("utcTime"))
    match={"id":f"fotmob:event:{target['id']}","home":target["home"]["name"],"away":target["away"]["name"],
           "league":f"fotmob:league:{league_id}","kickoff":ko.isoformat(),"sport":"football",
           "format":"REGULATION_90","competition_profile":"LOWER"}
    ev=[]
    for k,v in (("home_team",match["home"]),("away_team",match["away"]),("format","REGULATION_90")):
        ev.append({"id":f"{match['id']}:{k}","key":k,"value":v,"kind":"FACT","source_id":SOURCE,
                   "published_at":asof,"received_at":asof,"observed_at":asof,"critical":True,"supports":[]})
    return {"match":match,"as_of":asof,
            "sources":[{"id":SOURCE,"independence_group":"fotmob-direct-json","reliability":.82,"enabled":True}],
            "evidence":ev,"history":history}

def entry_threshold(probs,edge=.03):
    w,p,l=probs
    return None if w<=0 else 1+(l+edge)/w

def rs(row):
    raw=row["raw"]; stress=row["stress_probabilities"]
    return {"key":row["key"],"market":row["market"],
            "p_win":round(raw[0],4),"p_push":round(raw[1],4),"p_loss":round(raw[2],4),
            "fair":round(fair_odds(raw[0],raw[1]),3) if raw[0]>0 else None,
            "entry3":round(max(entry_threshold(x,.03) for x in stress if x[0]>0),3),
            "entry5":round(max(entry_threshold(x,.05) for x in stress if x[0]>0),3),
            "selection_status":row["selection_status"],
            "loss_scores":[{"score":f"{x['home']}:{x['away']}","p":round(x["p"],4)}
                           for x in row["death_test"]["top_score_losses"][:4]]}

def grid_summary(grid):
    rows=[rs(r) for r in grid["candidates"]]
    # Practical price-blind shortlist: avoid trivial prices and explicit scenario conflicts.
    eligible=[r for r in rows if r["selection_status"]=="NO_EXPLICIT_CONFLICT"
              and r["fair"] is not None and 1.45<=r["fair"]<=3.10]
    def robustness(r):
        # approximate normalized quality: high model hit probability with moderate fair price
        return (r["p_win"]/(r["p_win"]+r["p_loss"]) if r["p_win"]+r["p_loss"] else 0)
    best=sorted(eligible,key=lambda r:(-robustness(r),r["entry5"],r["key"]))[:10]
    worst=sorted(eligible,key=lambda r:(robustness(r),-r["entry5"],r["key"]))[:8]
    return rows,best,worst

def lookup(rows,contract):
    for r in rows:
        if r["market"]==contract:return r
    return None

def build_eval(bg,legs):
    want=sorted(json.dumps(x,sort_keys=True,separators=(",",":")) for x in legs)
    for r in bg["candidates"]:
        got=sorted(json.dumps(x,sort_keys=True,separators=(",",":")) for x in r["legs"])
        if got==want:
            return {"legs":r["legs"],"p_joint":round(r["joint_probability_raw"],4),
                    "fair":round(r["fair_odds_raw"],3) if r["fair_odds_raw"] else None,
                    "sensitivity_min":round(r["sensitivity_probability_min"],4),
                    "robust_break_even":round(r["sensitivity_break_even_odds_raw"],3) if r["sensitivity_break_even_odds_raw"] else None,
                    "selection_status":r["selection_status"]}
    return None

def top_builders(bg):
    out=[]
    for r in bg["candidates"]:
        if r["selection_status"]!="NO_EXPLICIT_CONFLICT":continue
        p=r["joint_probability_raw"]; floor=r["sensitivity_probability_min"]
        if not p or not (.25<=p<=.70):continue
        out.append({"legs":r["legs"],"p_joint":round(p,4),"fair":round(1/p,3),
                    "sensitivity_min":round(floor,4),
                    "robust_break_even":round(1/floor,3) if floor else None})
    return sorted(out,key=lambda x:(-x["sensitivity_min"],x["fair"]))[:5]

def flatten_stats(node,out):
    if isinstance(node,dict):
        key=node.get("key") or node.get("title") or node.get("name")
        vals=node.get("stats")
        if isinstance(key,str) and isinstance(vals,list) and len(vals)>=2:
            def n(v):
                if isinstance(v,(int,float)):return float(v)
                if isinstance(v,str):
                    m=re.search(r"-?\\d+(?:\\.\\d+)?",v.replace(",","."))
                    return float(m.group()) if m else None
                return None
            a,b=n(vals[0]),n(vals[1])
            if a is not None and b is not None:out[re.sub(r"[^a-z0-9]","",key.casefold())]=(a,b)
        for v in node.values():flatten_stats(v,out)
    elif isinstance(node,list):
        for v in node:flatten_stats(v,out)

def recent_finished(team_data,league_id,n=3):
    fx=(((team_data.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or [])
    rows=[x for x in fx if (x.get("status") or {}).get("finished")
          and int((x.get("tournament") or {}).get("leagueId") or -1)==int(league_id)]
    return rows[-n:]

def small_diag(target,league_id,cache,details_cache):
    records=[]
    for tid in (int(target["home"]["id"]),int(target["away"]["id"])):
        for e in recent_finished(team_page(tid,cache),league_id,3):
            eid=int(e["id"])
            if eid not in details_cache:
                try:details_cache[eid]=get("matchDetails",{"matchId":eid})
                except Exception:details_cache[eid]={}
            sm={};flatten_stats(((details_cache[eid].get("content") or {}).get("stats") or {}),sm)
            h=e.get("home") or {};a=e.get("away") or {}
            idx=0 if int(h.get("id") or -1)==tid else 1
            rec={"event_id":eid,"team_id":tid,"opponent":(a if idx==0 else h).get("name")}
            for raw,(hv,av) in sm.items():
                metric=None
                for alias,m in SMALL_MAP.items():
                    if alias in raw:metric=m;break
                if metric:
                    vals=(hv,av);rec[metric+"_for"]=vals[idx];rec[metric+"_against"]=vals[1-idx]
                    rec[metric+"_total"]=hv+av
            if len(rec)>3: records.append(rec)
    metrics={}
    for metric in ("CORNERS","SHOTS","SOT","FOULS","CARDS"):
        totals=[r[metric+"_total"] for r in records if metric+"_total" in r]
        if totals:metrics[metric]={"n":len(totals),"mean_total":round(mean(totals),2),
                                  "min":min(totals),"max":max(totals)}
    return {"status":"DESCRIPTIVE_RESEARCH_ONLY" if metrics else "NO_STAT_COVERAGE",
            "sampled_fixtures":len({r["event_id"] for r in records}),"metrics":metrics,
            "probability":None,"ev":None,"stake":0}

def scan():
    matches=all_matches();team_cache={};details_cache={}
    out={"status":"RUNNING","provider":"FOTMOB_UNOFFICIAL_RESEARCH","date":"2026-10-06",
         "coverage":{"requested":10,"covered":8,"uncovered":[
           {"label":"1 Podgorica - Lovcen","reason":"CURRENT_FIXTURE_ABSENT_FROM_FOTMOB; team feeds stale"},
           {"label":"3 Pontypridd - Llantwit","reason":"CURRENT_FIXTURE_ABSENT_FROM_FOTMOB; Llantwit absent"}
         ]},"matches":[]}
    for label,eid,user in TARGETS:
        item=matches.get(eid)
        if not item:
            out["matches"].append({"label":label,"status":"FIXTURE_MISSING"});continue
        target=item["match"];league_id=item["league"].get("primaryId") or item["league"].get("id")
        try:
            hist=history_for(target,league_id,team_cache)
            sp=sports(target,league_id,hist)
            repo=Repository(Path("/tmp")/f"fotmob_{eid}.sqlite")
            try:
                pol=Policy()
                svc=Service(repo,pol)
                pred=svc.capture(sp,POOL)
                grid=create_grid(pred,pol,pred["sealed_at"])
                rows,best,worst=grid_summary(grid)
                try:bg=create_builder_grid(grid,pred,pol,pred["sealed_at"])
                except Exception:bg=None
                user_eval=build_eval(bg,user["builder"]) if ("builder" in user and bg) else lookup(rows,user)
                row={"label":label,"status":"OK","fixture":{"id":eid,"home":target["home"]["name"],
                     "away":target["away"]["name"],"kickoff":(target.get("status") or {}).get("utcTime"),
                     "league":item["league"].get("name"),"league_id":league_id},
                     "history_n":len(hist),"rates":pred["model"]["rates"],
                     "team_games":pred["model"]["team_games"],"effective_games":pred["model"]["effective_games"],
                     "score_scenarios":pred["model"]["score_scenarios"][:8],
                     "issues":[x["code"] for x in pred["issues"]],
                     "user_forecast":user,"user_evaluation":user_eval,
                     "best_big":best,"worst_big":worst,
                     "top_builders":top_builders(bg) if bg else [],
                     "small":small_diag(target,league_id,team_cache,details_cache)}
                out["matches"].append(row)
            finally:repo.close()
        except Exception as exc:
            out["matches"].append({"label":label,"status":"ERROR","error":type(exc).__name__+":"+str(exc)})
    out["status"]="DONE";return out

app=Flask(__name__);RESULT={"status":"BOOTING"}
def worker():
    global RESULT
    try:RESULT=scan()
    except Exception as e:RESULT={"status":"ERROR","error":type(e).__name__+":"+str(e)}
    print("SEFIROT_FOTMOB_FULL="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)
threading.Thread(target=worker,daemon=True).start()
@app.get("/health")
def health():return jsonify({"ok":True,"status":RESULT.get("status"),"matches":len(RESULT.get("matches",[]))})
@app.get("/last")
def last():return jsonify(RESULT)
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
