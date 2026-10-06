"""Temporary targeted current-odds probe for four Oct 6 UEFA Nations League forecasts."""
import os, json, urllib.request, urllib.parse, statistics
if os.environ.get("SEFIROT_FORECAST_ODDS_PROBE")=="1":
    KEY=os.environ.get("SEFIROT_ODDS_API_KEY","")
    SPORT="soccer_uefa_nations_league"
    targets={
      ("England","Czech Republic"),
      ("Croatia","Spain"),
      ("Switzerland","North Macedonia"),
      ("Scotland","Slovenia"),
    }
    def req(url):
        r=urllib.request.Request(url,headers={"Accept":"application/json"})
        with urllib.request.urlopen(r,timeout=30) as x:
            return json.loads(x.read().decode()),dict(x.headers)
    def med(xs): return round(statistics.median(xs),4) if xs else None
    try:
        evs,h=req("https://api.the-odds-api.com/v4/sports/"+SPORT+"/events?apiKey="+urllib.parse.quote(KEY))
        picked=[e for e in evs if (e.get("home_team"),e.get("away_team")) in targets]
        out={"status":"OK","events":[],"quota_before":{"remaining":h.get("x-requests-remaining"),"used":h.get("x-requests-used")}}
        last=h
        for e in picked:
            markets="h2h,spreads,alternate_spreads,totals,alternate_totals,btts"
            u=("https://api.the-odds-api.com/v4/sports/"+SPORT+"/events/"+e["id"]+"/odds?"
               +urllib.parse.urlencode({"apiKey":KEY,"regions":"eu","markets":markets,"oddsFormat":"decimal"}))
            od,last=req(u)
            buckets={}
            for b in od.get("bookmakers",[]):
                for m in b.get("markets",[]):
                    key=m.get("key")
                    for o in m.get("outcomes",[]):
                        p=o.get("price"); pt=o.get("point"); nm=o.get("name")
                        if not isinstance(p,(int,float)): continue
                        if key=="h2h": k=("h2h",nm,None)
                        elif key=="btts": k=("btts",nm,None)
                        elif key in ("totals","alternate_totals"): k=("total",nm,pt)
                        elif key in ("spreads","alternate_spreads"): k=("spread",nm,pt)
                        else: continue
                        buckets.setdefault(k,[]).append(p)
            rows=[]
            for (mkt,side,line),vals in buckets.items():
                rows.append({"market":mkt,"side":side,"line":line,"median":med(vals),"best":round(max(vals),4),"n":len(vals)})
            out["events"].append({"home":e["home_team"],"away":e["away_team"],"commence_time":e["commence_time"],"rows":rows})
        out["quota_after"]={"remaining":last.get("x-requests-remaining"),"used":last.get("x-requests-used")}
        print("SEFIROT_FORECAST_ODDS="+json.dumps(out,separators=(",",":"),ensure_ascii=True),flush=True)
    except Exception as exc:
        print("SEFIROT_FORECAST_ODDS="+json.dumps({"status":"FAILED","error":type(exc).__name__+":"+str(exc)},separators=(",",":")),flush=True)
