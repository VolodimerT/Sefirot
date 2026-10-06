"""Temporary read-only corners audit for Switzerland-North Macedonia."""
import json

def _corner_value(stats, team_id):
    for block in stats:
        if ((block.get("team") or {}).get("id")) != team_id:
            continue
        for row in block.get("statistics") or []:
            if str(row.get("type","")).lower()=="corner kicks":
                v=row.get("value")
                try: return int(v or 0)
                except: return 0
    return None

def run(get):
    out={"status":"BOOTING","match":"Switzerland - North Macedonia","rows":[]}
    try:
        pack=get("fixtures",{"date":"2026-10-06","timezone":"UTC"})
        target=None
        for r in pack["data"]["response"]:
            hn=str((r.get("teams") or {}).get("home",{}).get("name","")).lower()
            an=str((r.get("teams") or {}).get("away",{}).get("name","")).lower()
            if hn=="switzerland" and ("macedonia" in an):
                target=r; break
        if not target: raise ValueError("target_not_found")
        teams=[target["teams"]["home"],target["teams"]["away"]]
        for team in teams:
            tid=team["id"]; name=team["name"]
            fp=get("fixtures",{"team":tid,"last":10,"status":"FT"})
            games=[]
            for g in fp["data"]["response"]:
                fid=g["fixture"]["id"]
                sp=get("fixtures/statistics",{"fixture":fid})
                stats=sp["data"]["response"]
                own=_corner_value(stats,tid)
                opp_id=g["teams"]["away"]["id"] if g["teams"]["home"]["id"]==tid else g["teams"]["home"]["id"]
                opp=_corner_value(stats,opp_id)
                if own is None or opp is None: continue
                games.append({
                    "fixture_id":fid,
                    "date":g["fixture"]["date"],
                    "venue":"HOME" if g["teams"]["home"]["id"]==tid else "AWAY",
                    "opponent":g["teams"]["away"]["name"] if g["teams"]["home"]["id"]==tid else g["teams"]["home"]["name"],
                    "corners_for":own,"corners_against":opp,"diff":own-opp,
                    "cover_minus_4_5":(own-opp)>4.5
                })
            n=len(games)
            out["rows"].append({
                "team":name,"team_id":tid,"n":n,
                "avg_for":sum(x["corners_for"] for x in games)/n if n else None,
                "avg_against":sum(x["corners_against"] for x in games)/n if n else None,
                "avg_diff":sum(x["diff"] for x in games)/n if n else None,
                "cover_minus_4_5":sum(1 for x in games if x["cover_minus_4_5"]),
                "games":games
            })
        out["status"]="DONE"
    except Exception as exc:
        out={"status":"ERROR","error":type(exc).__name__+":"+str(exc)}
    print("SEFIROT_SWISS_CORNERS="+json.dumps(out,separators=(",",":"),ensure_ascii=True),flush=True)
