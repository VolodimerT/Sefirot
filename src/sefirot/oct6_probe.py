"""Temporary read-only 2026-10-06 Nations League price-blind SEFIROT probe."""
import json
from .contracts import Policy
from .probability import estimate
from ._payoffs import Market, probabilities, fair_odds

DATE = "2026-10-06"

def _line(mass, variants, market):
    w,p,l = probabilities(market, mass)
    stress = [probabilities(market, v)[0] for v in variants]
    return {"key":market.key,"p_win_raw":w,"p_push_raw":p,"p_loss_raw":l,
            "fair_raw":fair_odds(w,p) if w>0 else None,
            "stress_win_min":min(stress),"stress_win_max":max(stress)}

def run(get, normalize_sports):
    out={"status":"BOOTING","date":DATE,"source":"API_FOOTBALL_V3","mode":"RESEARCH_ONLY","matches":[]}
    try:
        target=get("fixtures",{"date":DATE,"timezone":"UTC"})
        rows=[r for r in target["data"]["response"]
              if "nations league" in str((r.get("league") or {}).get("name","")).lower()
              and (r.get("fixture") or {}).get("status",{}).get("short")=="NS"]
        leagues=sorted({(r["league"]["id"],r["league"].get("season")) for r in rows})
        history_by_league={}
        for lid,season in leagues:
            try: history_by_league[lid]=[get("fixtures",{"league":lid,"season":season,"status":"FT"})]
            except Exception as exc: history_by_league[lid]=[]
        policy=Policy()
        for r in rows:
            fid=r["fixture"]["id"]
            try:
                norm=normalize_sports(target,fid,history_by_league.get(r["league"]["id"],[]),
                                      profile="MEN",source_reliability=.90)
                sports=norm["sports"]; mass,variants,model=estimate(sports,policy)
                grid=[]
                specs=[
                    ("1X2","HOME",None),("1X2","DRAW",None),("1X2","AWAY",None),
                    ("DOUBLE_CHANCE","1X",None),("DOUBLE_CHANCE","X2",None),("DOUBLE_CHANCE","12",None),
                    ("DNB","HOME",None),("DNB","AWAY",None),
                    ("TOTAL","OVER",1.5),("TOTAL","UNDER",1.5),
                    ("TOTAL","OVER",2.5),("TOTAL","UNDER",2.5),
                    ("TOTAL","OVER",3.5),("TOTAL","UNDER",3.5),
                    ("BTTS","YES",None),("BTTS","NO",None),
                    ("TEAM_TOTAL","HOME_OVER",0.5),("TEAM_TOTAL","HOME_OVER",1.5),
                    ("TEAM_TOTAL","AWAY_OVER",0.5),("TEAM_TOTAL","AWAY_OVER",1.5),
                    ("HANDICAP","HOME",-0.5),("HANDICAP","HOME",-1.0),
                    ("HANDICAP","AWAY",-0.5),("HANDICAP","AWAY",-1.0)]
                for kind,side,line in specs:
                    grid.append(_line(mass,variants,Market(kind,side,line)))
                out["matches"].append({
                    "fixture_id":fid,"home":r["teams"]["home"]["name"],"away":r["teams"]["away"]["name"],
                    "kickoff":r["fixture"]["date"],"league":r["league"]["name"],"league_id":r["league"]["id"],
                    "season":r["league"].get("season"),"rates":model["rates"],
                    "team_games":model["team_games"],"effective_games":model["effective_games"],
                    "score_scenarios":model["score_scenarios"],"goal_thresholds":model["goal_thresholds"],
                    "history_status":"OK" if min(model["team_games"])>=policy.min_team_games else "INSUFFICIENT_HISTORY",
                    "missing_facts":norm["receipt"]["missing_facts"],"markets":grid})
            except Exception as exc:
                out["matches"].append({"fixture_id":fid,"home":r["teams"]["home"]["name"],
                                       "away":r["teams"]["away"]["name"],"kickoff":r["fixture"]["date"],
                                       "status":"ERROR","error":type(exc).__name__+":"+str(exc)})
        out["status"]="DONE"
    except Exception as exc:
        out={"status":"ERROR","date":DATE,"error":type(exc).__name__+":"+str(exc)}
    print("SEFIROT_OCT6_PROBE="+json.dumps(out,ensure_ascii=True,separators=(",",":")),flush=True)
