from __future__ import annotations
import json, os, time as _time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, jsonify

from sefirot.contracts import Policy
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.market_grid import create_grid
from sefirot.markets import fair_odds

BASE="https://www.fotmob.com/api/data/"
DATE="20261006"
SOURCE="fotmob-unofficial-research"
MAX_MATCHES=80
POOL=[
 {"kind":"1X2","side":"HOME"},
 {"kind":"DOUBLE_CHANCE","side":"1X"},
 {"kind":"DNB","side":"HOME"},
 {"kind":"HANDICAP","side":"HOME","line":-0.5},
 {"kind":"TOTAL","side":"OVER","line":2.5},
 {"kind":"BTTS","side":"YES"},
 {"kind":"TEAM_TOTAL","side":"HOME_OVER","line":1.5},
]

def utcnow(): return datetime.now(timezone.utc)
def parse_iso(s): return datetime.fromisoformat(str(s).replace("Z","+00:00")).astimezone(timezone.utc)

def get(path,params):
    url=BASE+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 SEFIROT/2.4.2 research"})
    with urllib.request.urlopen(req,timeout=25) as r:
        if r.status!=200: raise RuntimeError("FOTMOB_HTTP_"+str(r.status))
        data=json.loads(r.read().decode())
    if not isinstance(data,dict): raise RuntimeError("FOTMOB_INVALID_JSON")
    _time.sleep(.03)
    return data

def all_matches():
    d=get("matches",{"date":DATE})
    out=[]
    now=utcnow()
    for league in d.get("leagues") or []:
        lname=str(league.get("name") or "")
        # Avoid friendlies/youth where lineup/tactical uncertainty dominates.
        bad=("friendly","u17","u18","u19","u20","u21","youth")
        if any(x in lname.casefold() for x in bad): continue
        lid=league.get("primaryId") or league.get("id")
        for m in league.get("matches") or []:
            try: ko=parse_iso((m.get("status") or {}).get("utcTime"))
            except Exception: continue
            st=m.get("status") or {}
            if st.get("finished") or ko <= now+timedelta(minutes=25): continue
            if not m.get("id") or not lid: continue
            out.append({"match":m,"league":league,"league_id":lid,"kickoff":ko})
    out.sort(key=lambda x:x["kickoff"])
    return out[:MAX_MATCHES]

def team_page(tid,cache):
    if tid not in cache: cache[tid]=get("teams",{"id":tid})
    return cache[tid]

def history_for(target,league_id,cache):
    merged={}
    cutoff=utcnow()
    team_counts=[]
    for tid in (int(target["home"]["id"]),int(target["away"]["id"])):
        cnt=0
        d=team_page(tid,cache)
        fixtures=(((d.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or [])
        for e in fixtures:
            status=e.get("status") or {}; tourn=e.get("tournament") or {}
            if not status.get("finished"): continue
            if int(tourn.get("leagueId") or -1)!=int(league_id): continue
            try: ko=parse_iso(status["utcTime"])
            except Exception: continue
            if ko>=cutoff or (cutoff-ko).days>730: continue
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
        team_counts.append(cnt)
    return sorted(merged.values(),key=lambda x:x["kickoff"]),team_counts

def sports(target,league_id,history):
    asof=utcnow().isoformat(); ko=parse_iso((target.get("status") or {}).get("utcTime"))
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

def entry_threshold(probs,edge=.05):
    w,p,l=probs
    return None if w<=0 else 1+(l+edge)/w

def row_summary(row):
    raw=row["raw"]; stress=row["stress_probabilities"]
    fair=round(fair_odds(raw[0],raw[1]),3) if raw[0]>0 else None
    ent=max(entry_threshold(x,.05) for x in stress if x[0]>0)
    return {"key":row["key"],"market":row["market"],
            "p_win":round(raw[0],4),"p_push":round(raw[1],4),"p_loss":round(raw[2],4),
            "fair":fair,"entry5":round(ent,3),
            "premium":round(ent/fair-1,4) if fair else None,
            "selection_status":row["selection_status"],
            "loss_scores":[{"score":f"{x['home']}:{x['away']}","p":round(float(x.get("probability",x.get("p",0))),4)}
                           for x in row["death_test"]["top_score_losses"][:3]]}

def scan_one(item,cache):
    t=item["match"]; lid=item["league_id"]
    hist,counts=history_for(t,lid,cache)
    if len(hist)<18 or min(counts)<8: return None
    repo=Repository(Path("/tmp")/f"hunt_{t['id']}.sqlite")
    try:
        pol=Policy(); svc=Service(repo,pol); pred=svc.capture(sports(t,lid,hist),POOL)
        grid=create_grid(pred,pol,pred["sealed_at"])
        rows=[]
        for r in grid["candidates"]:
            if r["selection_status"]!="NO_EXPLICIT_CONFLICT": continue
            z=row_summary(r)
            if z["fair"] is None or not (1.35<=z["fair"]<=2.80): continue
            if z["p_win"]<0.48: continue
            if z["entry5"]>2.40: continue
            rows.append(z)
        rows.sort(key=lambda z:(z["premium"],-z["p_win"],z["entry5"]))
        if not rows: return None
        return {
          "fixture":{"id":int(t["id"]),"home":t["home"]["name"],"away":t["away"]["name"],
                     "kickoff":item["kickoff"].isoformat(),"league":item["league"].get("name")},
          "history_n":len(hist),"team_counts":counts,
          "rates":pred["model"]["rates"],"effective_games":pred["model"]["effective_games"],
          "issues":[x["code"] for x in pred["issues"]],
          "candidates":rows[:6]
        }
    finally: repo.close()

def hunt():
    cache={}; matches=all_matches(); out=[]; errors=[]
    for i,item in enumerate(matches):
        try:
            r=scan_one(item,cache)
            if r: out.append(r)
        except Exception as e:
            errors.append({"id":item["match"].get("id"),"error":type(e).__name__+":"+str(e)})
    flat=[]
    for m in out:
        for c in m["candidates"]:
            flat.append({"fixture":m["fixture"],"history_n":m["history_n"],"team_counts":m["team_counts"],
                         "rates":m["rates"],"issues":m["issues"],**c})
    flat.sort(key=lambda z:(z["premium"],-z["p_win"],-z["history_n"]))
    # One primary candidate per fixture first; keep diversity.
    chosen=[]; seen=set()
    for z in flat:
        fid=z["fixture"]["id"]
        if fid in seen: continue
        seen.add(fid); chosen.append(z)
        if len(chosen)>=24: break
    return {"status":"DONE","date":"2026-10-06","scanned_upcoming":len(matches),
            "qualified_matches":len(out),"top":chosen,"errors":errors[:20]}

app=Flask(__name__); RESULT={"status":"BOOTING"}
def run():
    global RESULT
    try: RESULT=hunt()
    except Exception as e: RESULT={"status":"ERROR","error":type(e).__name__+":"+str(e)}
    print("SEFIROT_VALUE_HUNT="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)

import threading
threading.Thread(target=run,daemon=True).start()
@app.get("/health")
def health(): return jsonify({"ok":True,"status":RESULT.get("status"),"top":len(RESULT.get("top",[]))})
@app.get("/last")
def last(): return jsonify(RESULT)
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
