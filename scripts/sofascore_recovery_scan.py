from __future__ import annotations
import json, math, os, re, threading, time as _time, unicodedata
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from flask import Flask, jsonify
from curl_cffi import requests

from sefirot.contracts import Policy
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.market_grid import create_grid
from sefirot.builder_research import create_builder_grid
from sefirot.markets import fair_odds

DATE="2026-10-06"
SOURCE="sofascore-fallback"
BASE="https://api.sofascore.com/api/v1"
TARGETS=[
 ("Podgorica - Lovcen",["Podgorica"],["Lovcen","Lovćen"],{"kind":"TEAM_TOTAL","side":"HOME_OVER","line":1.5}),
 ("Skjetten - Kongsvinger 2",["Skjetten"],["Kongsvinger 2","Kongsvinger II"],{"kind":"HANDICAP","side":"HOME","line":-1.0}),
 ("Pontypridd - Llantwit",["Pontypridd"],["Llantwit Major","Llantwit"],{"kind":"TOTAL","side":"OVER","line":3.0}),
 ("Braintree - Walton & Hersham",["Braintree","Braintree Town"],["Walton & Hersham","Walton and Hersham"],{"kind":"TEAM_TOTAL","side":"HOME_OVER","line":1.5}),
 ("Dartford - Ramsgate",["Dartford"],["Ramsgate"],{"kind":"TOTAL","side":"OVER","line":2.5}),
 ("Maldon & Tiptree - Welling",["Maldon & Tiptree","Maldon and Tiptree"],["Welling","Welling United"],{"kind":"TOTAL","side":"OVER","line":3.0}),
 ("Alfreton - FC United",["Alfreton","Alfreton Town"],["FC United","FC United of Manchester"],{"builder":[{"kind":"DOUBLE_CHANCE","side":"1X"},{"kind":"TOTAL","side":"OVER","line":1.5}]}),
 ("Curzon Ashton - Redcar",["Curzon Ashton"],["Redcar","Redcar Athletic"],{"kind":"BTTS","side":"YES"}),
 ("Stockton - Bury",["Stockton","Stockton Town"],["Bury"],{"kind":"TEAM_TOTAL","side":"AWAY_OVER","line":1.5}),
 ("Emley - Bamber Bridge",["Emley","AFC Emley"],["Bamber Bridge"],{"kind":"TOTAL","side":"OVER","line":2.5}),
]
POOL=[
 {"kind":"1X2","side":"HOME"},{"kind":"1X2","side":"DRAW"},{"kind":"1X2","side":"AWAY"},
 {"kind":"TOTAL","side":"OVER","line":2.5},{"kind":"TOTAL","side":"UNDER","line":2.5},
 {"kind":"BTTS","side":"YES"},{"kind":"BTTS","side":"NO"},
]
STAT_KEYS={
 "corners":{"cornerkicks","corners","cornerkickswon"},
 "shots":{"totalshots","shots"},
 "sot":{"shotsongoal","shotson target","shotsontarget"},
 "cards":{"yellowcards","yellow cards"},
 "fouls":{"fouls"},
}

def now():
    return datetime.now(timezone.utc)

def iso(ts):
    return datetime.fromtimestamp(ts,tz=timezone.utc).isoformat()

def canon(s):
    s=unicodedata.normalize("NFKD",str(s)).casefold()
    return "".join(c for c in s if c.isalnum())

def score(actual, aliases):
    c=canon(actual); best=0
    for a in aliases:
        t=canon(a)
        if c==t: best=max(best,4)
        elif len(c)>=4 and len(t)>=4 and (c in t or t in c): best=max(best,3)
        else:
            ac=set(re.findall(r"[a-z0-9]+",unicodedata.normalize("NFKD",str(actual)).casefold()))
            at=set(re.findall(r"[a-z0-9]+",unicodedata.normalize("NFKD",str(a)).casefold()))
            if ac and at and ac&at: best=max(best,1)
    return best

class Sofa:
    def __init__(self):
        self.s=requests.Session(impersonate="chrome")
        self.cache={}
    def get(self,path):
        if path in self.cache: return self.cache[path]
        u=BASE+path
        r=self.s.get(u,headers={"accept":"application/json","referer":"https://www.sofascore.com/"},
                     timeout=20)
        if r.status_code!=200: raise RuntimeError(f"SOFA_HTTP_{r.status_code}")
        d=r.json()
        if not isinstance(d,dict): raise RuntimeError("SOFA_INVALID_JSON")
        self.cache[path]=d
        _time.sleep(.06)
        return d

def pick_fixture(events, ha, aa):
    ranked=[]
    for e in events:
        h=(e.get("homeTeam") or {}).get("name",""); a=(e.get("awayTeam") or {}).get("name","")
        hs,as_=score(h,ha),score(a,aa)
        if hs and as_: ranked.append((hs+as_,e))
    ranked.sort(key=lambda x:x[0],reverse=True)
    if not ranked: raise RuntimeError("FIXTURE_NOT_FOUND")
    if len(ranked)>1 and ranked[0][0]==ranked[1][0]: raise RuntimeError("FIXTURE_AMBIGUOUS")
    return ranked[0][1]

def finished(e):
    return (e.get("status") or {}).get("type")=="finished" and \
           isinstance((e.get("homeScore") or {}).get("current"),(int,float)) and \
           isinstance((e.get("awayScore") or {}).get("current"),(int,float))

def event_league_id(e):
    t=e.get("tournament") or {}
    u=t.get("uniqueTournament") or {}
    return str(u.get("id") or t.get("id") or "unknown")

def hist_rows(sofa,target,limit=24):
    home_id=target["homeTeam"]["id"]; away_id=target["awayTeam"]["id"]
    league=event_league_id(target); cutoff=now()
    merged={}
    for tid in (home_id,away_id):
        for page in (0,1):
            try: d=sofa.get(f"/team/{tid}/events/last/{page}")
            except Exception:
                if page==0: raise
                break
            for e in d.get("events") or []:
                if not finished(e): continue
                if event_league_id(e)!=league: continue
                merged[e["id"]]=e
            if not d.get("hasNextPage"): break
    rows=[]
    for e in sorted(merged.values(),key=lambda x:x.get("startTimestamp",0))[-limit*2:]:
        st=int(e["startTimestamp"])
        if datetime.fromtimestamp(st,tz=timezone.utc)>=cutoff: continue
        ft=datetime.fromtimestamp(st,tz=timezone.utc)+timedelta(hours=3)
        rows.append({
          "id":f"sofa:event:{e['id']}",
          "home":e["homeTeam"]["name"],"away":e["awayTeam"]["name"],
          "league":f"sofa:tournament:{league}",
          "kickoff":iso(st),"finished_at":min(ft,cutoff-timedelta(seconds=1)).isoformat(),
          "received_at":cutoff.isoformat(),
          "home_goals":int(e["homeScore"]["current"]),"away_goals":int(e["awayScore"]["current"]),
          "source_id":SOURCE,"competition_profile":"LOWER",
        })
    return rows[-40:]

def evidence(target,asof):
    vals=[("home_team",target["homeTeam"]["name"]),("away_team",target["awayTeam"]["name"]),
          ("format","REGULATION_90")]
    out=[]
    for k,v in vals:
        out.append({"id":f"sofa:{target['id']}:{k}","key":k,"value":v,"kind":"FACT","source_id":SOURCE,
                    "observed_at":asof,"published_at":asof,"received_at":asof,"critical":True,"supports":[]})
    return out

def sports(target,history):
    asof=now().isoformat(); league=event_league_id(target)
    kickoff=iso(int(target["startTimestamp"]))
    return {
      "match":{"id":f"sofa:event:{target['id']}","home":target["homeTeam"]["name"],
               "away":target["awayTeam"]["name"],"league":f"sofa:tournament:{league}",
               "kickoff":kickoff,"sport":"football","format":"REGULATION_90","competition_profile":"LOWER"},
      "as_of":asof,
      "sources":[{"id":SOURCE,"independence_group":"sofascore-direct-json","reliability":.82,"enabled":True}],
      "evidence":evidence(target,asof),
      "history":history,
    }

def threshold(w,p,l,target=.03):
    if w<=0: return None
    return 1+(l+target)/w

def row_summary(row):
    raw=row["raw"]; stress=row["stress_probabilities"]
    th=[threshold(x[0],x[1],x[2],.03) for x in stress if x[0]>0]
    return {
      "key":row["key"],"market":row["market"],
      "p_win":round(raw[0],4),"p_push":round(raw[1],4),"p_loss":round(raw[2],4),
      "fair":round(fair_odds(raw[0],raw[1]),3) if raw[0]>0 else None,
      "entry_3pct_stress":round(max(th),3) if th else None,
      "selection_status":row["selection_status"],
      "top_score_losses":row["death_test"]["top_score_losses"][:5],
    }

def rank_grid(grid):
    rows=[row_summary(r) for r in grid["candidates"] if r["selection_status"]=="NO_EXPLICIT_CONFLICT"]
    # cleanest first: low loss, then low robust break-even
    best=sorted(rows,key=lambda r:(r["p_loss"],r["entry_3pct_stress"] or 999,r["key"]))[:12]
    worst=sorted(rows,key=lambda r:(-r["p_loss"],-(r["entry_3pct_stress"] or 0),r["key"]))[:8]
    return best,worst

def find_market(grid, contract):
    if "builder" in contract: return None
    for r in grid["candidates"]:
        if r["market"]==contract: return row_summary(r)
    return None

def find_builder(bg, legs):
    if not legs: return None
    def k(x): return json.dumps(x,sort_keys=True,separators=(",",":"))
    want=sorted(k(x) for x in legs)
    for r in bg["candidates"]:
        if sorted(k(x) for x in r["legs"])==want:
            return {"legs":r["legs"],"p_joint":round(r["joint_probability_raw"],4),
                    "fair":round(r["fair_odds_raw"],3) if r["fair_odds_raw"] else None,
                    "sensitivity_min":round(r["sensitivity_probability_min"],4),
                    "robust_break_even":round(r["sensitivity_break_even_odds_raw"],3) if r["sensitivity_break_even_odds_raw"] else None,
                    "selection_status":r["selection_status"]}
    return None

def builder_top(bg):
    rows=[]
    for r in bg["candidates"]:
        if r["selection_status"]!="NO_EXPLICIT_CONFLICT": continue
        rows.append({"legs":r["legs"],"p_joint":round(r["joint_probability_raw"],4),
                     "fair":round(r["fair_odds_raw"],3) if r["fair_odds_raw"] else None,
                     "sensitivity_min":round(r["sensitivity_probability_min"],4),
                     "robust_break_even":round(r["sensitivity_break_even_odds_raw"],3) if r["sensitivity_break_even_odds_raw"] else None})
    return sorted(rows,key=lambda x:(-x["sensitivity_min"],x["fair"] or 999))[:4]

def stat_map(d):
    out={}
    for period in d.get("statistics") or []:
        if period.get("period") not in ("ALL","ALL_PERIODS",None): continue
        for g in period.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                key=canon(it.get("key") or it.get("name") or "")
                hv=it.get("homeValue",it.get("home"))
                av=it.get("awayValue",it.get("away"))
                def num(v):
                    if isinstance(v,(int,float)): return float(v)
                    if isinstance(v,str):
                        m=re.search(r"-?\d+(?:\.\d+)?",v.replace(",","."))
                        return float(m.group()) if m else None
                    return None
                h,a=num(hv),num(av)
                if h is not None and a is not None: out[key]=(h,a)
    return out

def match_metric(sm,name):
    aliases=STAT_KEYS[name]
    for k,v in sm.items():
        if k in aliases or any(a in k or k in a for a in aliases): return v
    return None

def small_snapshot(sofa,target):
    result={}
    league=event_league_id(target)
    team_ids=[target["homeTeam"]["id"],target["awayTeam"]["id"]]
    for tid in team_ids:
        evs=[]
        for page in (0,1):
            try:d=sofa.get(f"/team/{tid}/events/last/{page}")
            except: break
            evs += [e for e in d.get("events") or [] if finished(e) and event_league_id(e)==league]
            if not d.get("hasNextPage"): break
        evs=sorted({e["id"]:e for e in evs}.values(),key=lambda x:x["startTimestamp"],reverse=True)[:6]
        obs=[]
        for e in evs:
            try: sm=stat_map(sofa.get(f"/event/{e['id']}/statistics"))
            except: continue
            side="home" if e["homeTeam"]["id"]==tid else "away"
            idx=0 if side=="home" else 1; oi=1-idx
            rec={"event_id":e["id"],"opponent":e["awayTeam"]["name"] if idx==0 else e["homeTeam"]["name"]}
            for name in STAT_KEYS:
                vv=match_metric(sm,name)
                if vv: rec[name+"_for"]=vv[idx];rec[name+"_against"]=vv[oi];rec[name+"_total"]=vv[0]+vv[1]
            obs.append(rec)
        result[str(tid)]={"team":target["homeTeam"]["name"] if tid==team_ids[0] else target["awayTeam"]["name"],
                          "n":len(obs),"observations":obs}
    # Descriptive candidates; never monetary.
    def vals(tid,key):
        return [x[key] for x in result[str(tid)]["observations"] if key in x]
    h,a=team_ids
    cand=[]
    for metric,lines in [("corners",[7.5,8.5,9.5,10.5]),("shots",[21.5,23.5,25.5,27.5]),("cards",[2.5,3.5,4.5,5.5])]:
        sample=vals(h,metric+"_total")+vals(a,metric+"_total")
        if len(sample)>=6:
            avg=mean(sample)
            for line in lines:
                cover=sum(v>line for v in sample)/len(sample)
                if cover>=.67:
                    cand.append({"metric":metric,"market":"TOTAL_OVER","line":line,"sample_n":len(sample),
                                 "sample_mean":round(avg,2),"cover":round(cover,3)})
                    break
    for tid,label in [(h,"HOME"),(a,"AWAY")]:
        opp=a if tid==h else h
        for metric,lines in [("corners",[2.5,3.5,4.5,5.5]),("shots",[7.5,9.5,11.5,13.5])]:
            own=vals(tid,metric+"_for"); allowed=vals(opp,metric+"_against")
            if len(own)>=3 and len(allowed)>=3:
                est=(mean(own)+mean(allowed))/2
                for line in lines:
                    if est>=line+1.0:
                        cand.append({"metric":metric,"market":label+"_OVER","line":line,
                                     "sample_n":min(len(own),len(allowed)),"expected_descriptive":round(est,2)})
                        break
    return {"status":"DESCRIPTIVE_RESEARCH_ONLY","teams":result,"candidates":cand[:8],
            "probability":None,"ev":None,"stake":0}

def scan():
    sofa=Sofa()
    sched=sofa.get(f"/sport/football/scheduled-events/{DATE}")
    events=sched.get("events") or []
    output={"status":"RUNNING","date":DATE,"provider":"SOFASCORE_UNOFFICIAL_FALLBACK",
            "provider_contract":"CREDENTIAL_FREE_READ_ONLY_JSON","matches":[],"errors":[]}
    for label,ha,aa,user in TARGETS:
        try:
            target=pick_fixture(events,ha,aa)
            hist=hist_rows(sofa,target)
            sp=sports(target,hist)
            repo=Repository(Path("/tmp")/f"sf_{target['id']}.sqlite")
            try:
                policy=Policy()
                svc=Service(repo,policy)
                pred=svc.capture(sp,POOL)
                grid=create_grid(pred,policy,pred["sealed_at"])
                bg=create_builder_grid(grid,pred,policy,pred["sealed_at"])
                best,worst=rank_grid(grid)
                user_eval=find_builder(bg,user["builder"]) if "builder" in user else find_market(grid,user)
                rates=pred["model"]["rates"]; tg=pred["model"]["team_games"]; eff=pred["model"]["effective_games"]
                row={"label":label,"fixture":{"id":target["id"],"home":target["homeTeam"]["name"],
                      "away":target["awayTeam"]["name"],"kickoff":iso(int(target["startTimestamp"])),
                      "tournament":(target.get("tournament") or {}).get("name")},
                     "history_n":len(hist),"rates":rates,"team_games":tg,"effective_games":eff,
                     "score_scenarios":pred["model"]["score_scenarios"][:8],
                     "issues":[i["code"] for i in pred["issues"]],
                     "user_forecast":user,"user_evaluation":user_eval,
                     "best_big":best,"worst_big":worst,"top_builders":builder_top(bg)}
                try: row["small"]=small_snapshot(sofa,target)
                except Exception as exc: row["small"]={"status":"UNAVAILABLE","error":type(exc).__name__}
                output["matches"].append(row)
            finally:
                repo.close()
        except Exception as exc:
            output["errors"].append({"label":label,"error":type(exc).__name__+":"+str(exc)})
    output["status"]="DONE"
    return output

app=Flask(__name__)
RESULT={"status":"BOOTING"}
def worker():
    global RESULT
    try: RESULT=scan()
    except Exception as exc: RESULT={"status":"ERROR","error":type(exc).__name__+":"+str(exc)}
    print("SEFIROT_SOFA_RECOVERY="+json.dumps(RESULT,separators=(",",":"),ensure_ascii=True),flush=True)

@app.get("/health")
def health(): return jsonify({"ok":True,"status":RESULT.get("status"),"matches":len(RESULT.get("matches",[]))})
@app.get("/last")
def last(): return jsonify(RESULT)

threading.Thread(target=worker,daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
