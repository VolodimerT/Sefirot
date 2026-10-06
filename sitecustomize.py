"""Temporary startup-only Swiss corner audit for Oct 6."""
import os, json, urllib.request, urllib.parse
if os.environ.get("SEFIROT_SWISS_CORNERS_PROBE")=="1":
    KEY=os.environ.get("API_FOOTBALL_KEY","")
    def api(path,params):
        u="https://v3.football.api-sports.io/"+path+"?"+urllib.parse.urlencode(params)
        r=urllib.request.Request(u,headers={"x-apisports-key":KEY,"Accept":"application/json"})
        with urllib.request.urlopen(r,timeout=30) as x:
            data=json.loads(x.read().decode())
        if data.get("errors"): raise ValueError("provider:"+str(data.get("errors")))
        return data.get("response") or []
    def cval(stats,tid):
        for b in stats:
            if ((b.get("team") or {}).get("id"))!=tid: continue
            for r in b.get("statistics") or []:
                if str(r.get("type","")).lower()=="corner kicks":
                    try: return int(r.get("value") or 0)
                    except: return 0
        return None
    try:
        fixtures=api("fixtures",{"date":"2026-10-06","timezone":"UTC"})
        target=None
        for r in fixtures:
            hn=str(r["teams"]["home"]["name"]).lower(); an=str(r["teams"]["away"]["name"]).lower()
            if hn=="switzerland" and "macedonia" in an:
                target=r; break
        if target is None: raise ValueError("target_not_found")
        out={"status":"OK","teams":[]}
        for t in [target["teams"]["home"],target["teams"]["away"]]:
            tid=t["id"]; name=t["name"]; fp=api("fixtures",{"team":tid,"last":10,"status":"FT"})
            games=[]
            for g in fp:
                fid=g["fixture"]["id"]; stats=api("fixtures/statistics",{"fixture":fid})
                own=cval(stats,tid)
                oid=g["teams"]["away"]["id"] if g["teams"]["home"]["id"]==tid else g["teams"]["home"]["id"]
                opp=cval(stats,oid)
                if own is None or opp is None: continue
                games.append({"date":g["fixture"]["date"],"venue":"HOME" if g["teams"]["home"]["id"]==tid else "AWAY",
                              "opponent":g["teams"]["away"]["name"] if g["teams"]["home"]["id"]==tid else g["teams"]["home"]["name"],
                              "for":own,"against":opp,"diff":own-opp})
            n=len(games)
            out["teams"].append({"team":name,"n":n,
                "avg_for":round(sum(x["for"] for x in games)/n,2) if n else None,
                "avg_against":round(sum(x["against"] for x in games)/n,2) if n else None,
                "avg_diff":round(sum(x["diff"] for x in games)/n,2) if n else None,
                "covers_m4_5":sum(1 for x in games if x["diff"]>=5),"games":games})
        print("SEFIROT_SWISS_CORNERS="+json.dumps(out,separators=(",",":"),ensure_ascii=True),flush=True)
    except Exception as exc:
        print("SEFIROT_SWISS_CORNERS="+json.dumps({"status":"FAILED","error":type(exc).__name__+":"+str(exc)},separators=(",",":")),flush=True)
